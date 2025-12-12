"""Command-line interface for SyncAgent.

Provides commands for:
- init: Initialize a new keystore
- unlock: Unlock the keystore with password
- export-key: Export the encryption key
- import-key: Import an encryption key
- register-protocol: Register syncfile:// URL handler
- unregister-protocol: Unregister syncfile:// URL handler
- open-url: Handle a syncfile:// URL
- tray: Start the system tray icon
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import click

from syncagent.client.keystore import (
    KeyStoreError,
    create_keystore,
    load_keystore,
)
from syncagent.client.protocol import (
    InvalidURLError,
    RegistrationError,
    SecurityError,
    handle_url,
    is_registered,
    register_protocol,
    unregister_protocol,
)


def get_config_dir() -> Path:
    """Get the configuration directory for SyncAgent.

    Returns:
        Path to ~/.syncagent or equivalent.
    """
    return Path.home() / ".syncagent"


@click.group()
@click.version_option()
def cli() -> None:
    """SyncAgent - Zero-Knowledge E2EE file synchronization."""


@cli.command()
def init() -> None:
    """Initialize a new SyncAgent keystore.

    Creates a new encryption key and stores it securely.
    You will be prompted to create a master password and choose a sync folder.
    """
    config_dir = get_config_dir()

    # Check if already initialized
    if (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent already initialized.", err=True)
        click.echo(f"Keystore exists at: {config_dir / 'keyfile.json'}", err=True)
        click.echo("\nTo start over, run:")
        click.echo("  syncagent reset")
        sys.exit(1)

    click.echo("Welcome to SyncAgent!")
    click.echo("This wizard will help you set up secure file synchronization.\n")

    # Prompt for password with confirmation
    click.echo("First, create a master password to protect your encryption key.")
    click.echo("Choose a strong password - you'll need it to unlock SyncAgent.\n")

    password = click.prompt(
        "Create master password",
        hide_input=True,
        confirmation_prompt="Confirm master password",
    )

    # Prompt for sync folder
    default_sync_folder = Path.home() / "SyncAgent"
    click.echo("\nWhere do you want to sync files?")
    sync_folder_input = click.prompt(
        "Sync folder",
        default=str(default_sync_folder),
        show_default=True,
    )
    sync_path = Path(sync_folder_input).expanduser().resolve()

    try:
        keystore = create_keystore(password, config_dir)

        # Create sync folder if it doesn't exist
        if not sync_path.exists():
            sync_path.mkdir(parents=True)
            click.echo(f"\nCreated sync folder: {sync_path}")

        # Save sync folder to config
        config = load_config()
        config["sync_folder"] = str(sync_path)
        save_config(config)

        click.echo("\nSyncAgent initialized successfully!")
        click.echo(f"Key ID: {keystore.key_id}")
        click.echo(f"Config directory: {config_dir}")
        click.echo(f"Sync folder: {sync_path}")

        # Next steps guidance
        click.echo("\n" + "=" * 50)
        click.echo("NEXT STEPS:")
        click.echo("=" * 50)
        click.echo("\n1. Start the server (if not already running):")
        click.echo("   uvicorn syncagent.server.app:app --host 0.0.0.0 --port 8000")
        click.echo("\n2. Open http://localhost:8000 and create an admin account")
        click.echo("\n3. Go to 'Invitations' and create a token for this machine")
        click.echo("\n4. Register this machine with the server:")
        click.echo(
            "   syncagent register --server http://localhost:8000 --token <invitation-token>"
        )

    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def reset(force: bool) -> None:
    """Reset SyncAgent configuration.

    Deletes the config directory (~/.syncagent) to allow re-initialization.
    This will NOT delete your sync folder or synced files.

    WARNING: This will delete your encryption key! Make sure you have
    exported it first if you need to recover your files.
    """
    import shutil

    config_dir = get_config_dir()

    if not config_dir.exists():
        click.echo("Nothing to reset. SyncAgent is not initialized.")
        return

    if not force:
        click.echo("WARNING: This will delete your SyncAgent configuration, including:")
        click.echo("  - Encryption key (keyfile.json)")
        click.echo("  - Server registration (config.json)")
        click.echo(f"\nConfig directory: {config_dir}")
        click.echo("\nYour sync folder and files will NOT be deleted.")
        click.echo("\nMake sure you have exported your encryption key if needed:")
        click.echo("  syncagent export-key\n")

        if not click.confirm("Are you sure you want to reset?"):
            click.echo("Aborted.")
            return

    try:
        shutil.rmtree(config_dir)
        click.echo("SyncAgent configuration has been reset.")
        click.echo("Run 'syncagent init' to set up again.")
    except OSError as e:
        click.echo(f"Error deleting config directory: {e}", err=True)
        sys.exit(1)


@cli.command()
def unlock() -> None:
    """Unlock the SyncAgent keystore.

    Decrypts and caches the encryption key for use.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        click.echo("Keystore unlocked successfully!")
        click.echo(f"Key ID: {keystore.key_id}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("export-key")
def export_key() -> None:
    """Export the encryption key.

    Outputs the base64-encoded encryption key.
    Use this to transfer your key to another device.

    WARNING: Keep this key secret! Anyone with this key
    can decrypt your files.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        key_b64 = keystore.export_key()
        click.echo("\nEncryption key (keep secret!):")
        click.echo(key_b64)
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("import-key")
@click.argument("key")
def import_key(key: str) -> None:
    """Import an encryption key.

    KEY is the base64-encoded encryption key from another device.

    This will replace your current encryption key.
    Make sure both devices use the same key to sync files.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        keystore.import_key(key)
        click.echo("Encryption key imported successfully!")
        click.echo(f"New Key ID: {keystore.key_id}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def get_sync_folder() -> Path:
    """Get the sync folder path.

    Returns:
        Path to the sync folder (configured or default ~/SyncAgent).
    """
    config = load_config()
    if config.get("sync_folder"):
        return Path(config["sync_folder"]).expanduser().resolve()
    return Path.home() / "SyncAgent"


def get_config_file() -> Path:
    """Get the path to the config file."""
    return get_config_dir() / "config.json"


def load_config() -> dict[str, str]:
    """Load configuration from config file."""
    import json

    config_file = get_config_file()
    if config_file.exists():
        return dict(json.loads(config_file.read_text()))
    return {}


def save_config(config: dict[str, str]) -> None:
    """Save configuration to config file."""
    import json

    config_file = get_config_file()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2))


def sanitize_machine_name(name: str) -> str:
    """Sanitize machine name to be safe for filenames.

    Only allows alphanumeric characters, hyphens, and underscores.
    Other characters are replaced with underscores.

    Args:
        name: The machine name to sanitize.

    Returns:
        Safe machine name.
    """
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def get_registered_machine_name() -> str | None:
    """Get the registered machine name from config.

    Returns:
        Machine name if registered, None otherwise.
    """
    config = load_config()
    return config.get("machine_name")


@cli.command()
@click.option(
    "--server",
    required=True,
    help="Server URL (e.g., http://localhost:8000).",
)
@click.option(
    "--token",
    required=True,
    help="Invitation token from the server admin.",
)
@click.option(
    "--name",
    default=None,
    help="Machine name (default: hostname).",
)
def register(server: str, token: str, name: str | None) -> None:
    """Register this machine with a SyncAgent server.

    Requires an invitation token from the server admin.
    Creates a connection between this machine and the server.
    """
    import platform
    import socket

    import httpx

    config_dir = get_config_dir()

    # Check if initialized
    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    # Check if already registered
    config = load_config()
    if config.get("server_url") and config.get("auth_token"):
        click.echo("Warning: This machine is already registered.", err=True)
        if not click.confirm("Do you want to re-register with a new server?"):
            sys.exit(0)

    # Determine machine name (sanitized for safe filenames)
    default_name = sanitize_machine_name(socket.gethostname())
    if name:
        machine_name = sanitize_machine_name(name)
        if machine_name != name:
            click.echo(f"Note: Machine name sanitized to '{machine_name}'")
    else:
        machine_name = click.prompt(
            "Machine name (alphanumeric, hyphens, underscores only)",
            default=default_name,
            show_default=True,
        )
        sanitized = sanitize_machine_name(machine_name)
        if sanitized != machine_name:
            click.echo(f"Note: Machine name sanitized to '{sanitized}'")
            machine_name = sanitized

    machine_platform = platform.system().lower()

    click.echo(f"\nRegistering machine '{machine_name}' with server...")

    # Call the registration API
    try:
        response = httpx.post(
            f"{server.rstrip('/')}/api/machines/register",
            json={
                "name": machine_name,
                "platform": machine_platform,
                "invitation_token": token,
            },
            timeout=30.0,
        )

        if response.status_code == 401:
            click.echo("Error: Invalid or expired invitation token.", err=True)
            sys.exit(1)
        elif response.status_code == 409:
            click.echo(f"Error: Machine name '{machine_name}' already exists on server.", err=True)
            click.echo("Use --name to specify a different name.")
            sys.exit(1)
        elif response.status_code != 201:
            detail = response.json().get("detail", "Unknown error")
            click.echo(f"Error: {detail}", err=True)
            sys.exit(1)

        data = response.json()
        auth_token = data["token"]
        machine_info = data["machine"]

        # Save configuration
        config["server_url"] = server.rstrip("/")
        config["auth_token"] = auth_token
        config["machine_name"] = machine_info["name"]
        save_config(config)

        click.echo("\nMachine registered successfully!")
        click.echo(f"Server: {server}")
        click.echo(f"Machine name: {machine_info['name']}")

    except httpx.ConnectError:
        click.echo(f"Error: Could not connect to server at {server}", err=True)
        click.echo("Make sure the server is running and accessible.")
        sys.exit(1)
    except httpx.RequestError as e:
        click.echo(f"Error: Request failed: {e}", err=True)
        sys.exit(1)


@cli.command("register-protocol")
def register_protocol_cmd() -> None:
    """Register the syncfile:// protocol handler.

    Registers SyncAgent as the handler for syncfile:// URLs
    on your operating system. This allows clicking links in
    the web dashboard to open files locally.
    """
    try:
        if is_registered():
            click.echo("Protocol handler is already registered.")
            return

        register_protocol()
        click.echo("Protocol handler registered successfully!")
        click.echo("You can now open syncfile:// URLs.")
    except RegistrationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("unregister-protocol")
def unregister_protocol_cmd() -> None:
    """Unregister the syncfile:// protocol handler.

    Removes SyncAgent as the handler for syncfile:// URLs.
    """
    try:
        if not is_registered():
            click.echo("Protocol handler is not registered.")
            return

        unregister_protocol()
        click.echo("Protocol handler unregistered successfully!")
    except RegistrationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("open-url")
@click.argument("url")
def open_url(url: str) -> None:
    """Open a syncfile:// URL.

    URL is the syncfile:// URL to open.

    This command is typically called by the operating system
    when clicking a syncfile:// link.
    """
    sync_folder = get_sync_folder()

    if not sync_folder.exists():
        click.echo(f"Error: Sync folder not found: {sync_folder}", err=True)
        sys.exit(1)

    try:
        file_path = handle_url(url, sync_folder)
        click.echo(f"Opened: {file_path}")
    except InvalidURLError as e:
        click.echo(f"Invalid URL: {e}", err=True)
        sys.exit(1)
    except SecurityError as e:
        click.echo(f"Security error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError as e:
        click.echo(f"File not found: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("protocol-status")
def protocol_status() -> None:
    """Check if the syncfile:// protocol handler is registered."""
    if is_registered():
        click.echo("Protocol handler: REGISTERED")
    else:
        click.echo("Protocol handler: NOT REGISTERED")
        click.echo("Run 'syncagent register-protocol' to enable syncfile:// links.")


@cli.command()
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
    from syncagent.client.sync import (
        ChangeScanner,
        EventQueue,
        SyncEventType,
        TransferType,
        WorkerPool,
    )
    from syncagent.core.config import ServerConfig

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
        max_workers=4,
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

        try:
            # Scan for changes and push events to queue
            scanner.scan()

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

            # Wait for all tasks to complete
            import time
            while pool.active_count > 0:
                time.sleep(0.1)

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

        except Exception as e:
            pool.stop()
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
    else:
        # Single sync
        run_sync()


@cli.command()
@click.option(
    "--dashboard-url",
    default="http://localhost:8000",
    help="URL to the web dashboard.",
)
def tray(dashboard_url: str) -> None:
    """Start the system tray icon.

    Runs the SyncAgent tray icon in the background, providing:
    - Status indicators (idle, syncing, error, conflict)
    - Quick access to sync folder and dashboard
    - Sync control (pause/resume, sync now)

    Requires pystray and pillow: pip install syncagent[tray]
    """
    try:
        from syncagent.client.tray import PYSTRAY_AVAILABLE, SyncAgentTray, TrayCallbacks
    except ImportError:
        click.echo(
            "Error: Tray dependencies not installed.\n" "Install with: pip install syncagent[tray]",
            err=True,
        )
        sys.exit(1)

    if not PYSTRAY_AVAILABLE:
        click.echo(
            "Error: pystray not available.\n" "Install with: pip install pystray pillow",
            err=True,
        )
        sys.exit(1)

    sync_folder = get_sync_folder()

    # Create sync folder if it doesn't exist
    if not sync_folder.exists():
        sync_folder.mkdir(parents=True)
        click.echo(f"Created sync folder: {sync_folder}")

    def on_quit() -> None:
        click.echo("SyncAgent tray icon stopped.")

    callbacks = TrayCallbacks(on_quit=on_quit)

    click.echo("Starting SyncAgent tray icon...")
    click.echo(f"Sync folder: {sync_folder}")
    click.echo(f"Dashboard: {dashboard_url}")
    click.echo("Press Ctrl+C or use tray menu to quit.")

    tray_icon = SyncAgentTray(sync_folder, dashboard_url, callbacks)

    # Use non-blocking mode with signal handler for clean Ctrl+C on Windows
    import signal
    import threading

    stop_event = threading.Event()

    def signal_handler(signum: int, frame: object) -> None:
        click.echo("\nStopping tray icon...")
        tray_icon.stop()
        stop_event.set()

    signal.signal(signal.SIGINT, signal_handler)

    # Start tray in background thread
    tray_icon.start(blocking=False)

    # Wait for stop signal or tray to close via menu
    try:
        while not stop_event.is_set():
            # Check if tray is still running (user may have quit via menu)
            if tray_icon._icon is None:
                break
            stop_event.wait(timeout=0.5)
    except KeyboardInterrupt:
        click.echo("\nStopping tray icon...")
        tray_icon.stop()


# === Server Commands ===


@cli.group()
def server() -> None:
    """Server management commands.

    These commands are for server administrators to manage the SyncAgent server.
    """


@server.command("purge-trash")
@click.option(
    "--older-than-days",
    "-d",
    type=int,
    default=None,
    help="Delete items older than N days (default: use server config).",
)
@click.option(
    "--db-path",
    type=click.Path(),
    default=None,
    help="Path to database file (default: SYNCAGENT_DB_PATH or ./syncagent.db).",
)
@click.option(
    "--storage-path",
    type=click.Path(),
    default=None,
    help="Path to local storage (default: SYNCAGENT_STORAGE_PATH or ./storage).",
)
def purge_trash_cmd(
    older_than_days: int | None,
    db_path: str | None,
    storage_path: str | None,
) -> None:
    """Purge old items from trash.

    Permanently deletes files that have been in trash longer than the
    specified number of days. Also removes associated chunk data from storage.

    This command can be run manually or via cron for scheduled cleanup.

    Examples:

        # Purge using server defaults (30 days)
        syncagent server purge-trash

        # Purge items older than 7 days
        syncagent server purge-trash --older-than-days 7

        # Use custom database path
        syncagent server purge-trash --db-path /var/lib/syncagent/syncagent.db
    """
    import os

    from syncagent.server.database import Database
    from syncagent.server.scheduler import purge_trash_with_storage
    from syncagent.server.storage import LocalFSStorage

    # Resolve paths from args or environment
    resolved_db_path = db_path or os.environ.get("SYNCAGENT_DB_PATH", "syncagent.db")
    resolved_storage_path = storage_path or os.environ.get("SYNCAGENT_STORAGE_PATH", "storage")

    # Default retention days
    default_days = int(os.environ.get("SYNCAGENT_TRASH_RETENTION_DAYS", "30"))
    days = older_than_days if older_than_days is not None else default_days

    db_file = Path(resolved_db_path)
    if not db_file.exists():
        click.echo(f"Error: Database not found: {db_file}", err=True)
        click.echo("Make sure the server has been run at least once.", err=True)
        sys.exit(1)

    click.echo(f"Database: {db_file}")
    click.echo(f"Storage: {resolved_storage_path}")
    click.echo(f"Purging items older than {days} days...")

    db = Database(db_file)
    storage = LocalFSStorage(resolved_storage_path)

    try:
        files_deleted, chunks_deleted = purge_trash_with_storage(db, storage, days)

        if files_deleted > 0:
            click.echo(f"Purged {files_deleted} files, {chunks_deleted} chunks deleted from storage.")
        else:
            click.echo("No items to purge.")
    finally:
        db.close()


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
