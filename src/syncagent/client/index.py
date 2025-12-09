"""Local file index using SQLite.

This module provides:
- Tracking of local file states
- Association of chunks with files
- Query interface for sync operations
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from pathlib import Path


class FileState(Enum):
    """State of a file in the sync system."""

    NEW = "new"  # File is new locally, needs upload
    MODIFIED = "modified"  # File was modified locally, needs upload
    DELETED = "deleted"  # File was deleted locally, needs remote delete
    SYNCED = "synced"  # File is in sync with remote
    CONFLICT = "conflict"  # File has a conflict


@dataclass
class FileEntry:
    """Represents a file in the local index."""

    path: str
    size: int
    mtime: datetime
    state: FileState
    content_hash: str | None = None
    version: int = 0


class FileIndex:
    """SQLite-based local file index.

    Tracks files, their states, and associated chunks for
    efficient sync operations.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the file index.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(self._db_path))
        self._conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS files (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime TEXT NOT NULL,
                state TEXT NOT NULL,
                content_hash TEXT,
                version INTEGER DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS chunks (
                file_path TEXT NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT NOT NULL,
                PRIMARY KEY (file_path, chunk_index),
                FOREIGN KEY (file_path) REFERENCES files(path) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_files_state ON files(state);
            CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_path);
        """)
        self._conn.execute("PRAGMA foreign_keys = ON")
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    def add_file(self, entry: FileEntry) -> None:
        """Add a new file to the index.

        Args:
            entry: File entry to add.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO files (path, size, mtime, state, content_hash, version)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                entry.path,
                entry.size,
                entry.mtime.isoformat(),
                entry.state.value,
                entry.content_hash,
                entry.version,
            ),
        )
        self._conn.commit()

    def get_file(self, path: str) -> FileEntry | None:
        """Get a file entry by path.

        Args:
            path: Path to the file.

        Returns:
            FileEntry if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_entry(row)

    def update_file(self, entry: FileEntry) -> None:
        """Update an existing file entry.

        Args:
            entry: File entry with updated values.
        """
        self._conn.execute(
            """
            UPDATE files
            SET size = ?, mtime = ?, state = ?, content_hash = ?, version = ?
            WHERE path = ?
            """,
            (
                entry.size,
                entry.mtime.isoformat(),
                entry.state.value,
                entry.content_hash,
                entry.version,
                entry.path,
            ),
        )
        self._conn.commit()

    def delete_file(self, path: str) -> None:
        """Delete a file from the index.

        Args:
            path: Path to the file to delete.
        """
        # Chunks are deleted automatically due to ON DELETE CASCADE
        self._conn.execute("DELETE FROM files WHERE path = ?", (path,))
        self._conn.commit()

    def list_files(
        self,
        state: FileState | None = None,
        prefix: str | None = None,
    ) -> list[FileEntry]:
        """List files in the index.

        Args:
            state: Optional state filter.
            prefix: Optional path prefix filter.

        Returns:
            List of matching file entries.
        """
        query = "SELECT * FROM files WHERE 1=1"
        params: list[str] = []

        if state is not None:
            query += " AND state = ?"
            params.append(state.value)

        if prefix is not None:
            query += " AND path LIKE ?"
            params.append(prefix + "%")

        cursor = self._conn.execute(query, params)
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    def get_pending_sync(self) -> list[FileEntry]:
        """Get files that need to be synced.

        Returns:
            List of files with state NEW, MODIFIED, or DELETED.
        """
        cursor = self._conn.execute(
            """
            SELECT * FROM files
            WHERE state IN (?, ?, ?)
            """,
            (FileState.NEW.value, FileState.MODIFIED.value, FileState.DELETED.value),
        )
        return [self._row_to_entry(row) for row in cursor.fetchall()]

    def set_file_chunks(self, path: str, chunk_hashes: list[str]) -> None:
        """Set the chunks for a file.

        Args:
            path: Path to the file.
            chunk_hashes: Ordered list of chunk hashes.
        """
        # Delete existing chunks
        self._conn.execute("DELETE FROM chunks WHERE file_path = ?", (path,))

        # Insert new chunks
        for i, chunk_hash in enumerate(chunk_hashes):
            self._conn.execute(
                "INSERT INTO chunks (file_path, chunk_index, chunk_hash) VALUES (?, ?, ?)",
                (path, i, chunk_hash),
            )
        self._conn.commit()

    def get_file_chunks(self, path: str) -> list[str]:
        """Get the chunks for a file.

        Args:
            path: Path to the file.

        Returns:
            Ordered list of chunk hashes.
        """
        cursor = self._conn.execute(
            """
            SELECT chunk_hash FROM chunks
            WHERE file_path = ?
            ORDER BY chunk_index
            """,
            (path,),
        )
        return [row["chunk_hash"] for row in cursor.fetchall()]

    def _row_to_entry(self, row: sqlite3.Row) -> FileEntry:
        """Convert a database row to a FileEntry.

        Args:
            row: Database row.

        Returns:
            FileEntry object.
        """
        return FileEntry(
            path=row["path"],
            size=row["size"],
            mtime=datetime.fromisoformat(row["mtime"]),
            state=FileState(row["state"]),
            content_hash=row["content_hash"],
            version=row["version"],
        )
