"""Server command for SyncAgent CLI.

Spec: docs/cli/server.md

Commands:
- server: Start the SyncAgent server
"""

from __future__ import annotations

import os
from pathlib import Path

import click


@click.command()
@click.option(
    "--host",
    "-h",
    default="0.0.0.0",
    help="Host to bind to.",
    show_default=True,
)
@click.option(
    "--port",
    "-p",
    type=int,
    default=8000,
    help="Port to listen on.",
    show_default=True,
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
    help="Path to chunk storage (default: SYNCAGENT_STORAGE_PATH or ./storage).",
)
@click.option(
    "--reload",
    is_flag=True,
    help="Enable auto-reload for development.",
)
def server(
    host: str,
    port: int,
    db_path: str | None,
    storage_path: str | None,
    reload: bool,
) -> None:
    """Start the SyncAgent server.

    Starts the file synchronization server using uvicorn.
    The server provides REST API, WebSocket status updates, and a web dashboard.

    Examples:

        # Start with defaults (0.0.0.0:8000)
        syncagent server

        # Start on specific port
        syncagent server --port 9000

        # Development mode with auto-reload
        syncagent server --reload
    """
    import uvicorn

    # Set environment variables for the server to pick up
    if db_path:
        os.environ["SYNCAGENT_DB_PATH"] = str(Path(db_path).resolve())
    if storage_path:
        os.environ["SYNCAGENT_STORAGE_PATH"] = str(Path(storage_path).resolve())

    # Resolve paths for display
    resolved_db = os.environ.get("SYNCAGENT_DB_PATH", "syncagent.db")
    resolved_storage = os.environ.get("SYNCAGENT_STORAGE_PATH", "storage")

    click.echo("Starting SyncAgent server...")
    click.echo(f"  Host: {host}")
    click.echo(f"  Port: {port}")
    click.echo(f"  Database: {resolved_db}")
    click.echo(f"  Storage: {resolved_storage}")
    if reload:
        click.echo("  Auto-reload: enabled")
    click.echo("")
    click.echo(f"Open http://{host if host != '0.0.0.0' else 'localhost'}:{port} to access the dashboard")
    click.echo("")

    # Run uvicorn
    uvicorn.run(
        "syncagent.server.app:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
    )
