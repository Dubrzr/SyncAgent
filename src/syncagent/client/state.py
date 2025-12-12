"""Local state management for sync client.

This module provides:
- SyncState: SQLite-based local state tracking
- File status tracking (synced, modified, pending_upload, conflict)
- Pending uploads queue
- Sync state persistence
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any


class FileStatus(Enum):
    """Status of a local file relative to server."""

    SYNCED = "synced"  # In sync with server
    MODIFIED = "modified"  # Locally modified, not yet uploaded
    PENDING_UPLOAD = "pending_upload"  # Queued for upload
    CONFLICT = "conflict"  # Conflict detected
    NEW = "new"  # New local file, not on server
    DELETED = "deleted"  # Locally deleted, needs server deletion


@dataclass
class LocalFile:
    """Represents a locally tracked file."""

    id: int
    path: str
    server_file_id: int | None
    server_version: int | None
    local_mtime: float | None
    local_size: int | None
    local_hash: str | None
    chunk_hashes: list[str]
    status: FileStatus
    last_synced_at: float | None

    @classmethod
    def from_row(cls, row: sqlite3.Row) -> LocalFile:
        """Create LocalFile from database row."""
        chunk_hashes = []
        if row["chunk_hashes"]:
            chunk_hashes = json.loads(row["chunk_hashes"])
        return cls(
            id=row["id"],
            path=row["path"],
            server_file_id=row["server_file_id"],
            server_version=row["server_version"],
            local_mtime=row["local_mtime"],
            local_size=row["local_size"],
            local_hash=row["local_hash"],
            chunk_hashes=chunk_hashes,
            status=FileStatus(row["status"]),
            last_synced_at=row["last_synced_at"],
        )


@dataclass
class PendingUpload:
    """Represents a pending upload."""

    id: int
    path: str
    detected_at: float
    attempts: int
    last_attempt_at: float | None
    error: str | None


@dataclass
class UploadProgress:
    """Tracks chunk-level upload progress for resume capability."""

    id: int
    path: str
    total_chunks: int
    uploaded_chunks: int
    chunk_hashes: list[str]  # Hashes of all chunks
    uploaded_hashes: list[str]  # Hashes of successfully uploaded chunks
    started_at: float
    updated_at: float

    @property
    def is_complete(self) -> bool:
        """Check if all chunks have been uploaded."""
        return self.uploaded_chunks >= self.total_chunks

    @property
    def percent(self) -> float:
        """Get upload progress percentage."""
        if self.total_chunks == 0:
            return 100.0
        return (self.uploaded_chunks / self.total_chunks) * 100


class SyncState:
    """SQLite-based local state for sync client."""

    def __init__(self, db_path: Path) -> None:
        """Initialize local state database.

        Args:
            db_path: Path to SQLite database file.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row

        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._create_tables()

    def _create_tables(self) -> None:
        """Create database tables if they don't exist."""
        self._conn.executescript("""
            -- Locally tracked files
            CREATE TABLE IF NOT EXISTS local_files (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                server_file_id INTEGER,
                server_version INTEGER,
                local_mtime REAL,
                local_size INTEGER,
                local_hash TEXT,
                chunk_hashes TEXT,
                status TEXT DEFAULT 'synced',
                last_synced_at REAL
            );

            CREATE INDEX IF NOT EXISTS idx_local_files_status
                ON local_files(status);

            -- Pending uploads queue
            CREATE TABLE IF NOT EXISTS pending_uploads (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                detected_at REAL NOT NULL,
                attempts INTEGER DEFAULT 0,
                last_attempt_at REAL,
                error TEXT
            );

            -- Key-value sync state
            CREATE TABLE IF NOT EXISTS sync_state (
                key TEXT PRIMARY KEY,
                value TEXT
            );

            -- Upload progress for chunk-level resume (Phase 12)
            CREATE TABLE IF NOT EXISTS upload_progress (
                id INTEGER PRIMARY KEY,
                path TEXT NOT NULL UNIQUE,
                total_chunks INTEGER NOT NULL,
                uploaded_chunks INTEGER DEFAULT 0,
                chunk_hashes TEXT NOT NULL,
                uploaded_hashes TEXT DEFAULT '[]',
                started_at REAL NOT NULL,
                updated_at REAL NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_upload_progress_path
                ON upload_progress(path);
        """)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # === File operations ===

    def add_file(
        self,
        path: str,
        *,
        local_mtime: float | None = None,
        local_size: int | None = None,
        local_hash: str | None = None,
        status: FileStatus = FileStatus.NEW,
    ) -> LocalFile:
        """Add a new file to tracking.

        Args:
            path: Relative path of the file.
            local_mtime: Local modification time.
            local_size: Local file size.
            local_hash: Hash of local content.
            status: Initial status.

        Returns:
            Created LocalFile record.
        """
        cursor = self._conn.execute(
            """
            INSERT INTO local_files (path, local_mtime, local_size, local_hash, status)
            VALUES (?, ?, ?, ?, ?)
            """,
            (path, local_mtime, local_size, local_hash, status.value),
        )
        self._conn.commit()

        return LocalFile(
            id=cursor.lastrowid or 0,
            path=path,
            server_file_id=None,
            server_version=None,
            local_mtime=local_mtime,
            local_size=local_size,
            local_hash=local_hash,
            chunk_hashes=[],
            status=status,
            last_synced_at=None,
        )

    def get_file(self, path: str) -> LocalFile | None:
        """Get a file by path.

        Args:
            path: Relative path of the file.

        Returns:
            LocalFile if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM local_files WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return LocalFile.from_row(row)

    def update_file(
        self,
        path: str,
        *,
        server_file_id: int | None = None,
        server_version: int | None = None,
        local_mtime: float | None = None,
        local_size: int | None = None,
        local_hash: str | None = None,
        chunk_hashes: list[str] | None = None,
        status: FileStatus | None = None,
        last_synced_at: float | None = None,
    ) -> None:
        """Update file metadata.

        Only provided parameters are updated.
        """
        updates: list[str] = []
        values: list[Any] = []

        if server_file_id is not None:
            updates.append("server_file_id = ?")
            values.append(server_file_id)
        if server_version is not None:
            updates.append("server_version = ?")
            values.append(server_version)
        if local_mtime is not None:
            updates.append("local_mtime = ?")
            values.append(local_mtime)
        if local_size is not None:
            updates.append("local_size = ?")
            values.append(local_size)
        if local_hash is not None:
            updates.append("local_hash = ?")
            values.append(local_hash)
        if chunk_hashes is not None:
            updates.append("chunk_hashes = ?")
            values.append(json.dumps(chunk_hashes))
        if status is not None:
            updates.append("status = ?")
            values.append(status.value)
        if last_synced_at is not None:
            updates.append("last_synced_at = ?")
            values.append(last_synced_at)

        if not updates:
            return

        values.append(path)
        self._conn.execute(
            f"UPDATE local_files SET {', '.join(updates)} WHERE path = ?",
            values,
        )
        self._conn.commit()

    def delete_file(self, path: str) -> None:
        """Delete a file from tracking.

        Args:
            path: Relative path of the file.
        """
        self._conn.execute("DELETE FROM local_files WHERE path = ?", (path,))
        self._conn.commit()

    def list_files(self, status: FileStatus | None = None) -> list[LocalFile]:
        """List tracked files.

        Args:
            status: Optional status filter.

        Returns:
            List of LocalFile records.
        """
        if status:
            cursor = self._conn.execute(
                "SELECT * FROM local_files WHERE status = ? ORDER BY path",
                (status.value,),
            )
        else:
            cursor = self._conn.execute("SELECT * FROM local_files ORDER BY path")

        return [LocalFile.from_row(row) for row in cursor.fetchall()]

    def mark_synced(
        self,
        path: str,
        server_file_id: int,
        server_version: int,
        chunk_hashes: list[str],
    ) -> None:
        """Mark a file as successfully synced.

        Args:
            path: Relative path.
            server_file_id: ID on server.
            server_version: Version on server.
            chunk_hashes: List of chunk hashes.
        """
        self.update_file(
            path,
            server_file_id=server_file_id,
            server_version=server_version,
            chunk_hashes=chunk_hashes,
            status=FileStatus.SYNCED,
            last_synced_at=time.time(),
        )

    def mark_modified(self, path: str) -> None:
        """Mark a file as locally modified."""
        self.update_file(path, status=FileStatus.MODIFIED)

    def mark_conflict(self, path: str) -> None:
        """Mark a file as having a conflict."""
        self.update_file(path, status=FileStatus.CONFLICT)

    def mark_deleted(self, path: str) -> None:
        """Mark a file as locally deleted (needs server deletion)."""
        self.update_file(path, status=FileStatus.DELETED)

    def remove_file(self, path: str) -> None:
        """Remove a file from the state database."""
        self._conn.execute("DELETE FROM local_files WHERE path = ?", (path,))
        self._conn.commit()

    # === Pending uploads ===

    def add_pending_upload(self, path: str) -> None:
        """Add a file to the pending upload queue.

        Args:
            path: Relative path of the file.
        """
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pending_uploads (path, detected_at, attempts)
            VALUES (?, ?, 0)
            """,
            (path, time.time()),
        )
        self._conn.commit()

    def get_pending_uploads(self) -> list[PendingUpload]:
        """Get all pending uploads ordered by detection time."""
        cursor = self._conn.execute(
            "SELECT * FROM pending_uploads ORDER BY detected_at"
        )
        return [
            PendingUpload(
                id=row["id"],
                path=row["path"],
                detected_at=row["detected_at"],
                attempts=row["attempts"],
                last_attempt_at=row["last_attempt_at"],
                error=row["error"],
            )
            for row in cursor.fetchall()
        ]

    def mark_upload_attempt(self, path: str, error: str | None = None) -> None:
        """Record an upload attempt.

        Args:
            path: Relative path.
            error: Error message if failed.
        """
        self._conn.execute(
            """
            UPDATE pending_uploads
            SET attempts = attempts + 1, last_attempt_at = ?, error = ?
            WHERE path = ?
            """,
            (time.time(), error, path),
        )
        self._conn.commit()

    def remove_pending_upload(self, path: str) -> None:
        """Remove a file from pending uploads.

        Args:
            path: Relative path.
        """
        self._conn.execute("DELETE FROM pending_uploads WHERE path = ?", (path,))
        self._conn.commit()

    def clear_pending_uploads(self) -> None:
        """Clear all pending uploads."""
        self._conn.execute("DELETE FROM pending_uploads")
        self._conn.commit()

    # === Sync state ===

    def get_state(self, key: str) -> str | None:
        """Get a sync state value.

        Args:
            key: State key.

        Returns:
            State value or None.
        """
        cursor = self._conn.execute(
            "SELECT value FROM sync_state WHERE key = ?",
            (key,),
        )
        row = cursor.fetchone()
        return row["value"] if row else None

    def set_state(self, key: str, value: str) -> None:
        """Set a sync state value.

        Args:
            key: State key.
            value: State value.
        """
        self._conn.execute(
            "INSERT OR REPLACE INTO sync_state (key, value) VALUES (?, ?)",
            (key, value),
        )
        self._conn.commit()

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
        """Get the last change cursor timestamp (ISO format).

        Used for incremental sync via /api/changes endpoint.
        """
        return self.get_state("last_change_cursor")

    def set_last_change_cursor(self, timestamp: str) -> None:
        """Set the last change cursor timestamp (ISO format).

        Used for incremental sync via /api/changes endpoint.
        """
        self.set_state("last_change_cursor", timestamp)

    # === Upload Progress (Phase 12) ===

    def start_upload_progress(
        self,
        path: str,
        chunk_hashes: list[str],
    ) -> UploadProgress:
        """Start tracking upload progress for a file.

        Args:
            path: Relative path of the file.
            chunk_hashes: List of all chunk hashes for the file.

        Returns:
            UploadProgress record.
        """
        now = time.time()
        self._conn.execute(
            """
            INSERT OR REPLACE INTO upload_progress
            (path, total_chunks, uploaded_chunks, chunk_hashes, uploaded_hashes, started_at, updated_at)
            VALUES (?, ?, 0, ?, '[]', ?, ?)
            """,
            (path, len(chunk_hashes), json.dumps(chunk_hashes), now, now),
        )
        self._conn.commit()

        return UploadProgress(
            id=0,
            path=path,
            total_chunks=len(chunk_hashes),
            uploaded_chunks=0,
            chunk_hashes=chunk_hashes,
            uploaded_hashes=[],
            started_at=now,
            updated_at=now,
        )

    def get_upload_progress(self, path: str) -> UploadProgress | None:
        """Get upload progress for a file.

        Args:
            path: Relative path of the file.

        Returns:
            UploadProgress if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM upload_progress WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        return UploadProgress(
            id=row["id"],
            path=row["path"],
            total_chunks=row["total_chunks"],
            uploaded_chunks=row["uploaded_chunks"],
            chunk_hashes=json.loads(row["chunk_hashes"]),
            uploaded_hashes=json.loads(row["uploaded_hashes"]),
            started_at=row["started_at"],
            updated_at=row["updated_at"],
        )

    def mark_chunk_uploaded(self, path: str, chunk_hash: str) -> None:
        """Mark a chunk as successfully uploaded.

        Args:
            path: Relative path of the file.
            chunk_hash: Hash of the uploaded chunk.
        """
        # Get current uploaded hashes
        progress = self.get_upload_progress(path)
        if progress is None:
            return

        # Add chunk hash if not already present
        if chunk_hash not in progress.uploaded_hashes:
            progress.uploaded_hashes.append(chunk_hash)

        self._conn.execute(
            """
            UPDATE upload_progress
            SET uploaded_chunks = ?, uploaded_hashes = ?, updated_at = ?
            WHERE path = ?
            """,
            (
                len(progress.uploaded_hashes),
                json.dumps(progress.uploaded_hashes),
                time.time(),
                path,
            ),
        )
        self._conn.commit()

    def clear_upload_progress(self, path: str) -> None:
        """Clear upload progress for a file (after successful upload).

        Args:
            path: Relative path of the file.
        """
        self._conn.execute("DELETE FROM upload_progress WHERE path = ?", (path,))
        self._conn.commit()

    def get_remaining_chunks(self, path: str) -> list[str]:
        """Get list of chunk hashes that haven't been uploaded yet.

        Args:
            path: Relative path of the file.

        Returns:
            List of chunk hashes still to upload.
        """
        progress = self.get_upload_progress(path)
        if progress is None:
            return []

        uploaded_set = set(progress.uploaded_hashes)
        return [h for h in progress.chunk_hashes if h not in uploaded_set]

    def clear_all_upload_progress(self) -> None:
        """Clear all upload progress records."""
        self._conn.execute("DELETE FROM upload_progress")
        self._conn.commit()
