"""Local state management for sync client.

This module provides:
- LocalSyncState: SQLite-based local state tracking
- SyncedFile: Represents a synchronized file

Architecture:
    The status (NEW, MODIFIED, SYNCED, DELETED) is computed on-the-fly
    by comparing tracked state with actual disk state. This simplifies
    the schema and eliminates state inconsistencies.

    Upload progress is not tracked locally - the server's chunk_exists()
    API is used to determine which chunks need uploading.
"""

from __future__ import annotations

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class FileStatus(Enum):
    """Derived status of a local file relative to server.

    Note: This status is computed, not stored. Use derive_status() function.
    """

    SYNCED = "synced"  # In sync with server (mtime/size match tracked)
    MODIFIED = "modified"  # Locally modified (mtime/size differ from tracked)
    NEW = "new"  # New local file (exists on disk but not tracked)
    DELETED = "deleted"  # Locally deleted (tracked but not on disk)
    CONFLICT = "conflict"  # Conflict state (for backwards compat)


@dataclass
class SyncedFile:
    """Represents a tracked file that has been synced with server.

    Attributes:
        path: Relative path from sync root.
        local_mtime: File modification time when last synced.
        local_size: File size when last synced.
        server_version: Server version number (for conflict detection).
        chunk_hashes: List of chunk hashes (for resume optimization).
        synced_at: Timestamp when file was synced.
    """

    path: str
    local_mtime: float
    local_size: int
    server_version: int
    chunk_hashes: list[str]
    synced_at: float

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> SyncedFile:
        """Create SyncedFile from database row."""
        chunk_hashes = []
        if row["chunk_hashes"]:
            chunk_hashes = json.loads(row["chunk_hashes"])
        return cls(
            path=row["path"],
            local_mtime=row["local_mtime"],
            local_size=row["local_size"],
            server_version=row["server_version"],
            chunk_hashes=chunk_hashes,
            synced_at=row["synced_at"],
        )


# Backwards compatibility alias
LocalFile = SyncedFile


def derive_status(
    path: str,
    tracked: SyncedFile | None,
    base_path: Path,
) -> FileStatus | None:
    """Derive file status by comparing tracked state with disk.

    Args:
        path: Relative path of the file.
        tracked: Tracked file info from database (or None).
        base_path: Base sync directory.

    Returns:
        FileStatus or None if file doesn't exist anywhere.
    """
    local_path = base_path / path

    if tracked is None:
        if local_path.exists():
            return FileStatus.NEW
        return None

    if not local_path.exists():
        return FileStatus.DELETED

    try:
        stat = local_path.stat()
        if stat.st_mtime > tracked.local_mtime or stat.st_size != tracked.local_size:
            return FileStatus.MODIFIED
    except OSError:
        # File might have been deleted between check and stat
        return FileStatus.DELETED

    return FileStatus.SYNCED


class LocalSyncState:
    """SQLite-based local state for sync client.

    This is a simplified state that only tracks synchronized files.
    File status is derived on-the-fly by comparing with disk state.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize local state database.

        Args:
            db_path: Path to SQLite database file.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Lock for thread-safe database access
        self._lock = threading.RLock()

        self._conn = sqlite3.connect(
            str(self._db_path),
            check_same_thread=False,
            isolation_level=None,  # Autocommit mode
        )
        self._conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            -- Simplified synced files table
            CREATE TABLE IF NOT EXISTS synced_files (
                path TEXT PRIMARY KEY,
                local_mtime REAL NOT NULL,
                local_size INTEGER NOT NULL,
                server_version INTEGER NOT NULL,
                chunk_hashes TEXT,
                synced_at REAL NOT NULL
            );

            -- Key-value sync state
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );
        """)

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # === File operations ===

    def get_file(self, path: str) -> SyncedFile | None:
        """Get a tracked file by path.

        Args:
            path: Relative path of the file.

        Returns:
            SyncedFile if found, None otherwise.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM synced_files WHERE path = ?",
                (path,),
            )
            row = cursor.fetchone()
        if row is None:
            return None
        return SyncedFile.from_row(row)

    def list_files(self) -> list[SyncedFile]:
        """List all tracked files.

        Returns:
            List of SyncedFile records.
        """
        with self._lock:
            cursor = self._conn.execute(
                "SELECT * FROM synced_files ORDER BY path"
            )
            rows = cursor.fetchall()
        return [SyncedFile.from_row(row) for row in rows]

    def mark_synced(
        self,
        path: str,
        server_file_id: int,  # Kept for backwards compat, ignored
        server_version: int,
        chunk_hashes: list[str],
        local_mtime: float,
        local_size: int,
    ) -> None:
        """Mark a file as successfully synced (upsert).

        Args:
            path: Relative path.
            server_file_id: Ignored (kept for backwards compatibility).
            server_version: Version on server.
            chunk_hashes: List of chunk hashes.
            local_mtime: Local file mtime (REQUIRED to detect future modifications).
            local_size: Local file size (REQUIRED to detect future modifications).
        """
        now = time.time()

        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO synced_files (
                    path, local_mtime, local_size, server_version, chunk_hashes, synced_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (path, local_mtime, local_size, server_version, json.dumps(chunk_hashes), now),
            )

    def update_file(
        self,
        path: str,
        *,
        local_mtime: float | None = None,
        local_size: int | None = None,
        server_version: int | None = None,
        chunk_hashes: list[str] | None = None,
        **kwargs: Any,  # Ignore other params for backwards compat
    ) -> None:
        """Update file metadata.

        Only provided parameters are updated.
        """
        updates: list[str] = []
        values: list[Any] = []

        if local_mtime is not None:
            updates.append("local_mtime = ?")
            values.append(local_mtime)
        if local_size is not None:
            updates.append("local_size = ?")
            values.append(local_size)
        if server_version is not None:
            updates.append("server_version = ?")
            values.append(server_version)
        if chunk_hashes is not None:
            updates.append("chunk_hashes = ?")
            values.append(json.dumps(chunk_hashes))

        if not updates:
            return

        updates.append("synced_at = ?")
        values.append(time.time())
        values.append(path)

        with self._lock:
            self._conn.execute(
                f"UPDATE synced_files SET {', '.join(updates)} WHERE path = ?",
                values,
            )

    def remove_file(self, path: str) -> None:
        """Remove a file from the state database."""
        with self._lock:
            self._conn.execute("DELETE FROM synced_files WHERE path = ?", (path,))

    # Alias for backwards compatibility
    delete_file = remove_file

    # === Backwards compatibility methods ===
    # These methods are kept for compatibility with existing code
    # that uses the old status-based API

    def add_file(
        self,
        path: str,
        *,
        local_mtime: float | None = None,
        local_size: int | None = None,
        local_hash: str | None = None,  # Ignored
        status: FileStatus = FileStatus.NEW,  # Ignored
    ) -> SyncedFile:
        """Add a new file to tracking.

        Note: In simplified state, we only track synced files.
        New files are implicitly tracked when they appear on disk.
        This method is kept for backwards compatibility but does nothing
        until the file is actually synced.
        """
        # In simplified state, we don't track un-synced files
        # Return a placeholder that indicates "not tracked"
        return SyncedFile(
            path=path,
            local_mtime=local_mtime or 0.0,
            local_size=local_size or 0,
            server_version=0,
            chunk_hashes=[],
            synced_at=0.0,
        )

    def mark_modified(self, path: str) -> None:
        """Mark a file as locally modified.

        Note: In simplified state, status is derived from disk state.
        This method is kept for backwards compatibility but does nothing.
        """
        pass  # Status is derived, not stored

    def mark_conflict(self, path: str) -> None:
        """Mark a file as having a conflict.

        Note: In simplified state, conflicts are handled differently.
        This method is kept for backwards compatibility but does nothing.
        """
        pass  # Conflicts are handled by creating .conflict-* files

    def mark_deleted(self, path: str) -> None:
        """Mark a file as locally deleted.

        Note: In simplified state, this removes the file from tracking.
        """
        self.remove_file(path)

    # === Sync state ===

    def get_state(self, key: str) -> str | None:
        """Get a sync state value."""
        with self._lock:
            cursor = self._conn.execute(
                "SELECT value FROM sync_state WHERE key = ?",
                (key,),
            )
            row = cursor.fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        """Set a sync state value."""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
                (key, value),
            )

    def get_last_sync_at(self) -> float | None:
        """Get timestamp of last successful sync."""
        value = self.get_state("last_sync_at")
        return float(value) if value else None

    def set_last_sync_at(self, timestamp: float) -> None:
        """Set timestamp of last successful sync."""
        self.set_state("last_sync_at", str(timestamp))

    def get_last_server_version(self) -> int | None:
        """Get last known server version."""
        value = self.get_state("last_server_version")
        return int(value) if value else None

    def set_last_server_version(self, version: int) -> None:
        """Set last known server version."""
        self.set_state("last_server_version", str(version))

    def get_last_change_cursor(self) -> str | None:
        """Get the last change cursor timestamp (ISO format)."""
        return self.get_state("last_change_cursor")

    def set_last_change_cursor(self, timestamp: str) -> None:
        """Set the last change cursor timestamp (ISO format)."""
        self.set_state("last_change_cursor", timestamp)

    # === Deprecated methods (no-op for backwards compatibility) ===

    def add_pending_upload(self, path: str) -> None:
        """Deprecated: Pending uploads are not tracked in simplified state."""
        pass

    def get_pending_uploads(self) -> list[Any]:
        """Deprecated: Returns empty list."""
        return []

    def mark_upload_attempt(self, path: str, error: str | None = None) -> None:
        """Deprecated: No-op."""
        pass

    def remove_pending_upload(self, path: str) -> None:
        """Deprecated: No-op."""
        pass

    def clear_pending_uploads(self) -> None:
        """Deprecated: No-op."""
        pass

    def start_upload_progress(
        self,
        path: str,
        chunk_hashes: list[str],
    ) -> Any:
        """Deprecated: Upload progress tracked via server chunk_exists()."""
        return None

    def get_upload_progress(self, path: str) -> Any:
        """Deprecated: Returns None."""
        return None

    def mark_chunk_uploaded(self, path: str, chunk_hash: str) -> None:
        """Deprecated: No-op."""
        pass

    def clear_upload_progress(self, path: str) -> None:
        """Deprecated: No-op."""
        pass

    def get_remaining_chunks(self, path: str) -> list[str]:
        """Deprecated: Returns empty list."""
        return []

    def clear_all_upload_progress(self) -> None:
        """Deprecated: No-op."""
        pass
