"""Sync command for SyncAgent CLI.

Spec: docs/cli/sync.md

Commands:
- sync: Synchronize files with the server
"""

from __future__ import annotations

import logging
import sys
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click

from syncagent.client.cli.config import (
    get_config_dir,
    get_sync_folder,
    load_config,
)
from syncagent.client.keystore import KeyStoreError, load_keystore


class StatusLineAwareHandler(logging.Handler):
    """Logging handler that coordinates with the status line display.

    Clears the status line before printing log messages and restores it after.
    """

    def __init__(
        self,
        clear_func: Callable[[], None],
        update_func: Callable[[], None],
        lock: threading.Lock,
    ) -> None:
        super().__init__()
        self._clear_func = clear_func
        self._update_func = update_func
        self._lock = lock

    def emit(self, record: logging.LogRecord) -> None:
        try:
            msg = self.format(record)
            with self._lock:
                self._clear_func()
                # Use stdout (same as status line) to prevent interleaving
                sys.stdout.write(msg + "\n")
                sys.stdout.flush()
                self._update_func()
        except Exception:
            self.handleError(record)


@click.command()
@click.option("--watch", "-w", is_flag=True, help="Watch for changes and sync continuously.")
@click.option("--no-progress", is_flag=True, help="Disable progress bars.")
def sync(watch: bool, no_progress: bool) -> None:
    """Synchronize files with the server.

    Uploads local changes and downloads remote changes.
    Use --watch to continuously monitor for changes.
    """
    from syncagent.client.api import HTTPClient
    from syncagent.client.notifications import notify_conflict
    from syncagent.client.state import LocalSyncState
    from syncagent.client.status import StatusReporter, StatusUpdate
    from syncagent.client.sync import (
        NETWORK_EXCEPTIONS,
        ChangeScanner,
        EventQueue,
        FileWatcher,
        RemoteChanges,
        SyncEvent,
        SyncEventType,
        TransferType,
        WorkerPool,
        emit_events,
        wait_for_network,
    )
    from syncagent.core.config import ServerConfig
    from syncagent.core.types import SyncState as SyncStateEnum

    config_dir = get_config_dir()

    # Check if initialized
    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    # Check if registered
    config = load_config()
    if not config.get("server_url") or not config.get("auth_token"):
        click.echo("Error: Not registered with a server. Run 'syncagent register' first.", err=True)
        sys.exit(1)

    # Unlock keystore
    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)

    # Get sync folder
    sync_folder = get_sync_folder()
    if not sync_folder.exists():
        sync_folder.mkdir(parents=True)
        click.echo(f"Created sync folder: {sync_folder}")

    server_config = ServerConfig(server_url=config["server_url"], token=config["auth_token"])
    client = HTTPClient(server_config)
    state_db_path = config_dir / "state.db"
    local_state = LocalSyncState(state_db_path)

    # Create event queue for sync events
    queue = EventQueue()

    # Create scanner to detect changes
    scanner = ChangeScanner(client, local_state, sync_folder)

    # Status reporter for dashboard updates AND receiving file change notifications
    # In watch mode, pass the queue so push notifications emit events
    status_reporter = StatusReporter(
        server_config,
        event_queue=queue if watch else None,
    )
    status_reporter.start()

    # Create worker pool for concurrent transfers
    pool = WorkerPool(
        client=client,
        encryption_key=keystore.encryption_key,
        base_path=sync_folder,
        state=local_state,
    )

    # Track results (completed transfers, not pending)
    uploaded: list[str] = []
    downloaded: list[str] = []
    deleted: list[str] = []
    conflicts: list[str] = []
    errors: list[str] = []

    # Track currently in-progress transfers for real-time display
    in_progress: dict[str, str] = {}  # path -> arrow symbol
    last_status_len = 0  # Track length of last status line for clearing
    progress_lock = threading.Lock()

    def clear_status_line() -> None:
        """Clear the current status line."""
        nonlocal last_status_len
        if last_status_len > 0 and not no_progress:
            # Move to start of line and clear it
            sys.stdout.write("\r" + " " * last_status_len + "\r")
            sys.stdout.flush()
            last_status_len = 0

    def update_status_line() -> None:
        """Update the real-time status line showing in-progress files."""
        nonlocal last_status_len
        if no_progress:
            return

        with progress_lock:
            if not in_progress:
                clear_status_line()
                return

            # Build status showing current files
            files_str = ", ".join(f"{arrow} {path}" for path, arrow in in_progress.items())
            status = f"  Syncing: {files_str}"

            # Truncate if too long
            term_width = 80
            if len(status) > term_width - 3:
                status = status[: term_width - 6] + "..."

            # Clear previous and write new
            clear_part = " " * max(0, last_status_len - len(status))
            sys.stdout.write(f"\r{status}{clear_part}")
            sys.stdout.flush()
            last_status_len = len(status)

    # Install status-line-aware logging handler to prevent log interleaving
    if not no_progress:
        status_handler = StatusLineAwareHandler(
            clear_func=clear_status_line,
            update_func=update_status_line,
            lock=progress_lock,
        )
        status_handler.setFormatter(logging.Formatter("%(message)s"))
        status_handler.setLevel(logging.WARNING)  # Only show warnings and errors

        # Replace handlers on syncagent logger to prevent interleaving
        syncagent_logger = logging.getLogger("syncagent")
        # Remove any existing handlers
        for handler in syncagent_logger.handlers[:]:
            syncagent_logger.removeHandler(handler)
        syncagent_logger.addHandler(status_handler)
        syncagent_logger.setLevel(logging.WARNING)
        # Prevent propagation to root logger
        syncagent_logger.propagate = False

    def make_on_complete(
        path: str, transfer_type: TransferType
    ) -> Callable[[Any], None]:
        """Create a completion callback that tracks the transfer."""
        def _on_complete(result: Any) -> None:
            with progress_lock:
                # Remove from in-progress
                in_progress.pop(path, None)

                if hasattr(result, "success") and result.success:
                    # Clear status line, print completion on new line
                    clear_status_line()

                    if transfer_type == TransferType.UPLOAD:
                        uploaded.append(path)
                        if not no_progress:
                            click.echo(f"  ↑ {path}")
                    elif transfer_type == TransferType.DOWNLOAD:
                        downloaded.append(path)
                        if not no_progress:
                            click.echo(f"  ↓ {path}")
                    elif transfer_type == TransferType.DELETE:
                        deleted.append(path)
                        if not no_progress:
                            click.echo(f"  ✗ {path}")
        return _on_complete

    def on_error(error_msg: str) -> None:
        """Track errors."""
        errors.append(error_msg)

    def process_event(event: SyncEvent) -> None:
        """Process a single sync event - submit to worker pool."""
        # Determine transfer type and arrow
        if event.event_type in (
            SyncEventType.LOCAL_CREATED,
            SyncEventType.LOCAL_MODIFIED,
        ):
            transfer_type = TransferType.UPLOAD
            arrow = "↑"
        elif event.event_type in (
            SyncEventType.REMOTE_CREATED,
            SyncEventType.REMOTE_MODIFIED,
        ):
            transfer_type = TransferType.DOWNLOAD
            arrow = "↓"
        elif event.event_type in (
            SyncEventType.LOCAL_DELETED,
            SyncEventType.REMOTE_DELETED,
        ):
            transfer_type = TransferType.DELETE
            arrow = "✗"
        else:
            return

        # Add to in-progress tracking
        with progress_lock:
            in_progress[event.path] = arrow

        # Submit to worker pool (logging happens on completion)
        pool.submit(
            event=event,
            transfer_type=transfer_type,
            on_complete=make_on_complete(event.path, transfer_type),
            on_error=on_error,
        )

    def fetch_and_emit_changes() -> None:
        """Fetch remote/local changes and emit events to queue."""
        # Fetch remote changes (with retry on network errors)
        remote_changes: RemoteChanges | None = None
        while remote_changes is None:
            try:
                remote_changes = scanner.fetch_remote_changes()
            except NETWORK_EXCEPTIONS as e:
                click.echo(f"Server unreachable: {e}")
                status_reporter.update_status(StatusUpdate(state=SyncStateEnum.OFFLINE))
                click.echo("Waiting for server to come back online...")
                wait_for_network(
                    client,
                    on_waiting=lambda: None,
                    on_restored=lambda: click.echo("Server is back online!"),
                )
                status_reporter.update_status(StatusUpdate(state=SyncStateEnum.SYNCING))

        # Scan local changes (no network needed)
        local_changes = scanner.scan_local_changes()

        # Emit events to queue
        emit_events(queue, local_changes, remote_changes)

    def process_queue_until_idle() -> None:
        """Process events from queue until pool is idle."""
        while True:
            event = queue.get(timeout=0.1)
            if event is not None:
                process_event(event)

            # Update real-time status display
            update_status_line()

            # Report progress to server (~100ms intervals via timeout)
            status_reporter.update_status(StatusUpdate(
                state=SyncStateEnum.SYNCING,
                files_pending=len(queue) + pool.queue_size,
                uploads_in_progress=pool.active_uploads,
                downloads_in_progress=pool.active_downloads,
                upload_speed=pool.upload_speed,
                download_speed=pool.download_speed,
            ))

            # Check if done (queue empty AND pool idle)
            if event is None and pool.active_count == 0 and pool.queue_size == 0:
                clear_status_line()  # Clear before exiting
                break

    def display_summary() -> None:
        """Display sync results summary."""
        if conflicts:
            click.echo(click.style("\nConflicts:", fg="yellow"))
            for path in conflicts:
                click.echo(f"  ! {path}")
                notify_conflict(Path(path).name, "another machine")

        if errors:
            click.echo(click.style("\nErrors:", fg="red"))
            for error in errors:
                click.echo(f"  ✗ {error}")

        total = len(uploaded) + len(downloaded) + len(deleted)
        if total == 0 and not conflicts and not errors:
            click.echo("Everything is up to date.")
        else:
            click.echo(
                f"\nSync complete: {len(uploaded)} uploaded, "
                f"{len(downloaded)} downloaded, "
                f"{len(deleted)} deleted, "
                f"{len(conflicts)} conflicts"
            )

    # =================================================================
    # Main sync logic
    # =================================================================

    click.echo(f"Syncing with {config['server_url']}...")
    click.echo(f"Sync folder: {sync_folder}\n")

    # Start pool (runs in background, processes submitted tasks)
    pool.start()
    status_reporter.update_status(StatusUpdate(state=SyncStateEnum.SYNCING))

    # Start watcher BEFORE scan to capture modifications during scan
    # The queue uses mtime-aware deduplication, so watcher events with
    # more recent mtime will win over scan events with stale mtime
    watcher = FileWatcher(sync_folder, queue)
    watcher.start()

    # Initial scan (always happens, whether watch or single mode)
    # Events from scanner and watcher arrive in parallel; queue deduplicates by mtime
    fetch_and_emit_changes()
    process_queue_until_idle()
    display_summary()

    if watch:
        # Watch mode: keep watcher running, process events continuously
        # StatusReporter handles both status reporting AND receiving push notifications
        click.echo("\nWatching for changes... (Ctrl+C to stop)\n")
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

        try:
            while True:
                event = queue.get(timeout=1.0)

                if event is not None:
                    click.echo(f"Detected change: {event.path}")
                    status_reporter.update_status(StatusUpdate(state=SyncStateEnum.SYNCING))

                    # Reset counters for this batch
                    uploaded.clear()
                    downloaded.clear()
                    deleted.clear()
                    errors.clear()

                    process_event(event)

                    # Process any additional queued events and wait for idle
                    process_queue_until_idle()

                    # Display mini-summary for this batch
                    parts = []
                    if uploaded:
                        parts.append(f"{len(uploaded)} uploaded")
                    if downloaded:
                        parts.append(f"{len(downloaded)} downloaded")
                    if deleted:
                        parts.append(f"{len(deleted)} deleted")
                    if errors:
                        parts.append(click.style(f"{len(errors)} errors", fg="red"))
                    if parts:
                        click.echo(f"  ✓ {', '.join(parts)}")

                    status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

        except KeyboardInterrupt:
            click.echo("\nStopping...")
    else:
        # Single sync mode: stop watcher after initial scan
        watcher.stop()

    # Cleanup (both modes)
    if watch:
        watcher.stop()
    pool.stop()

    if watch:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.OFFLINE))
    elif errors:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.ERROR))
    else:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

    status_reporter.stop()
