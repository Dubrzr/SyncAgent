"""Sync command for SyncAgent CLI.

Commands:
- sync: Synchronize files with the server
"""

from __future__ import annotations

import sys
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
    from syncagent.client.api import SyncClient
    from syncagent.client.notifications import notify_conflict
    from syncagent.client.state import SyncState
    from syncagent.client.status import StatusReporter, StatusUpdate
    from syncagent.client.sync import (
        NETWORK_EXCEPTIONS,
        ChangeScanner,
        EventQueue,
        RemoteChanges,
        SyncEventType,
        TransferType,
        WorkerPool,
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

    # Initialize sync components
    server_url = config["server_url"]
    auth_token = config["auth_token"]

    server_config = ServerConfig(server_url=server_url, token=auth_token)
    client = SyncClient(server_config)
    state_db = config_dir / "state.db"
    state = SyncState(state_db)

    # Create status reporter for real-time dashboard updates
    status_reporter = StatusReporter(server_config)
    status_reporter.start()

    # Create event queue for sync events
    queue = EventQueue()

    # Create scanner to detect changes
    scanner = ChangeScanner(client, state, sync_folder, queue)

    # Create worker pool for concurrent transfers
    pool = WorkerPool(
        client=client,
        encryption_key=keystore.encryption_key,
        base_path=sync_folder,
        state=state,
    )

    # Track results
    uploaded: list[str] = []
    downloaded: list[str] = []
    deleted: list[str] = []
    conflicts: list[str] = []
    errors: list[str] = []

    def on_complete(result: Any) -> None:
        """Track completed transfers."""
        pass  # Stats tracked in result lists

    def on_error(error_msg: str) -> None:
        """Track errors."""
        errors.append(error_msg)

    click.echo(f"Syncing with {server_url}...")
    click.echo(f"Sync folder: {sync_folder}\n")

    def run_sync() -> None:
        """Run a single sync operation."""
        nonlocal uploaded, downloaded, deleted, conflicts, errors

        # Reset counters
        uploaded = []
        downloaded = []
        deleted = []
        conflicts = []
        errors = []

        # Report syncing state
        status_reporter.update_status(StatusUpdate(state=SyncStateEnum.SYNCING))

        try:
            # Step 1: Fetch remote changes (with retry on network errors)
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

            # Step 2: Scan local changes (no network, won't fail)
            local_changes = scanner.scan_local_changes()

            # Step 3: Emit events to queue
            scanner.emit_events(local_changes, remote_changes)

            # Process events from queue
            pool.start()

            while True:
                event = queue.get(timeout=0.1)
                if event is None:
                    # Queue is empty, check if pool is idle
                    if pool.active_count == 0 and pool.queue_size == 0:
                        break
                    continue

                # Determine transfer type
                if event.event_type in (
                    SyncEventType.LOCAL_CREATED,
                    SyncEventType.LOCAL_MODIFIED,
                ):
                    transfer_type = TransferType.UPLOAD
                    uploaded.append(event.path)
                    arrow = "↑"
                elif event.event_type in (
                    SyncEventType.REMOTE_CREATED,
                    SyncEventType.REMOTE_MODIFIED,
                ):
                    transfer_type = TransferType.DOWNLOAD
                    downloaded.append(event.path)
                    arrow = "↓"
                elif event.event_type in (
                    SyncEventType.LOCAL_DELETED,
                    SyncEventType.REMOTE_DELETED,
                ):
                    transfer_type = TransferType.DELETE
                    deleted.append(event.path)
                    arrow = "✗"
                else:
                    continue

                if not no_progress:
                    click.echo(f"  {arrow} {event.path}")

                # Submit to worker pool
                pool.submit(
                    event=event,
                    transfer_type=transfer_type,
                    on_complete=on_complete,
                    on_error=on_error,
                )

                # Report progress with active counts and speeds
                status_reporter.update_status(StatusUpdate(
                    state=SyncStateEnum.SYNCING,
                    files_pending=len(queue) + pool.queue_size,
                    uploads_in_progress=pool.active_uploads,
                    downloads_in_progress=pool.active_downloads,
                    upload_speed=pool.upload_speed,
                    download_speed=pool.download_speed,
                ))

            # Wait for all tasks to complete, updating status every 500ms
            import time
            while pool.active_count > 0 or pool.queue_size > 0:
                time.sleep(0.5)
                # Keep reporting during wait with speeds
                status_reporter.update_status(StatusUpdate(
                    state=SyncStateEnum.SYNCING,
                    files_pending=pool.active_count + pool.queue_size,
                    uploads_in_progress=pool.active_uploads,
                    downloads_in_progress=pool.active_downloads,
                    upload_speed=pool.upload_speed,
                    download_speed=pool.download_speed,
                ))

            pool.stop()

            # Display results summary
            if conflicts:
                click.echo(click.style("\nConflicts:", fg="yellow"))
                for path in conflicts:
                    click.echo(f"  ! {path}")
                    # Send system notification
                    notify_conflict(Path(path).name, "another machine")

            if errors:
                click.echo(click.style("\nErrors:", fg="red"))
                for error in errors:
                    click.echo(f"  ✗ {error}")

            # Summary
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

            # Report final state
            if errors:
                status_reporter.update_status(StatusUpdate(state=SyncStateEnum.ERROR))
            else:
                status_reporter.update_status(StatusUpdate(state=SyncStateEnum.IDLE))

        except NETWORK_EXCEPTIONS as e:
            pool.stop()
            click.echo(f"Server connection lost: {e}")
            status_reporter.update_status(StatusUpdate(state=SyncStateEnum.OFFLINE))
            click.echo("Waiting for server to come back online...")
            wait_for_network(
                client,
                on_waiting=lambda: None,
                on_restored=lambda: click.echo("Server is back online!"),
            )
            # Retry sync after reconnection
            click.echo("Retrying sync...")
            run_sync()
        except Exception as e:
            pool.stop()
            status_reporter.update_status(StatusUpdate(state=SyncStateEnum.ERROR))
            click.echo(f"Sync error: {e}", err=True)

    if watch:
        # Continuous sync with file watching
        from syncagent.client.sync import FileWatcher

        click.echo("Watching for changes... (Ctrl+C to stop)\n")

        # Initial sync
        run_sync()

        # Create watcher that injects events into the queue
        watcher = FileWatcher(sync_folder, queue)
        try:
            watcher.start()
            # Keep running until interrupted
            while True:
                # Check for new events from watcher
                event = queue.get(timeout=1.0)
                if event is not None:
                    click.echo(f"\nDetected change: {event.path}, syncing...")
                    # Put event back and run sync
                    queue.put(event)
                    run_sync()
        except KeyboardInterrupt:
            click.echo("\nStopping...")
            watcher.stop()
            status_reporter.update_status(StatusUpdate(state=SyncStateEnum.OFFLINE))
            status_reporter.stop()
    else:
        # Single sync
        run_sync()
        status_reporter.stop()
