"""System tray command for SyncAgent CLI.

Commands:
- tray: Start the system tray icon
"""

from __future__ import annotations

import sys

import click

from syncagent.client.cli.config import get_sync_folder


@click.command()
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
