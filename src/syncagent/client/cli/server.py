"""Server administration commands for SyncAgent CLI.

Commands:
- server purge-trash: Purge old items from trash
"""

from __future__ import annotations

import sys
from pathlib import Path

import click


@click.group()
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
