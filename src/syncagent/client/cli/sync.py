"""Sync command for SyncAgent CLI.

Commands:
- sync: Synchronize files with the server
"""

from __future__ import annotations

import sys
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

    # Create status reporter for real-time dashboard updates
    status_reporter = StatusReporter(server_config)
    status_reporter.start()

    # Create scanner to detect changes
    scanner = ChangeScanner(client, local_state, sync_folder)

    # Create event queue for sync events
    queue = EventQueue()

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

    def make_on_complete(
        path: str, transfer_type: TransferType
    ) -> Callable[[Any], None]:
        """Create a completion callback that tracks the transfer."""
        def _on_complete(result: Any) -> None:
            if hasattr(result, "success") and result.success:
                if transfer_type == TransferType.UPLOAD:
                    uploaded.append(path)
                elif transfer_type == TransferType.DOWNLOAD:
                    downloaded.append(path)
                elif transfer_type == TransferType.DELETE:
                    deleted.append(path)
        return _on_complete

    def on_error(error_msg: str) -> None:
        """Track errors."""
        errors.append(error_msg)

    def process_event(event: SyncEvent) -> None:
        """Process a single sync event - submit to worker pool."""
        # Determine transfer type and display indicator
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

        if not no_progress:
            click.echo(f"  {arrow} {event.path}")

        # Submit to worker pool
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

    # Initial scan (always happens, whether watch or single mode)
    fetch_and_emit_changes()
    process_queue_until_idle()
    display_summary()

    if watch:
        # Watch mode: keep pool running, process watcher events
        click.echo("\nWatching for changes... (Ctrl+C to stop)\n")
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

        watcher = FileWatcher(sync_folder, queue)
        watcher.start()

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
            watcher.stop()

    # Cleanup (both modes)
    pool.stop()

    if watch:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.OFFLINE))
    elif errors:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.ERROR))
    else:
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

    status_reporter.stop()
