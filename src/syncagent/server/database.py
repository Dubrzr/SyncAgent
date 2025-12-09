"""Server database using SQLite with WAL mode.

This module provides:
- Machine registration and management
- Token-based authentication
- File metadata storage
- Chunk association
- Trash management
"""

from __future__ import annotations

import hashlib
import secrets
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path


def hash_token(token: str) -> str:
    """Hash a token using SHA-256.

    Args:
        token: Raw token string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(token.encode()).hexdigest()


@dataclass
class Machine:
    """Represents a registered machine."""

    id: int
    name: str
    platform: str
    created_at: datetime
    last_seen: datetime


@dataclass
class Token:
    """Represents an authentication token."""

    id: int
    machine_id: int
    token_hash: str
    created_at: datetime
    expires_at: datetime | None
    revoked: bool


@dataclass
class FileMetadata:
    """Represents file metadata on the server."""

    id: int
    path: str
    size: int
    content_hash: str
    version: int
    created_at: datetime
    updated_at: datetime
    updated_by: int  # machine_id
    deleted_at: datetime | None


class ConflictError(Exception):
    """Raised when a conflict is detected during file update."""


class Database:
    """SQLite database for server metadata.

    Uses WAL mode for better concurrency with multiple readers.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        # check_same_thread=False allows access from multiple threads
        # WAL mode handles concurrent access safely
        self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._setup()

    def _setup(self) -> None:
        """Set up database tables and configuration."""
        # Enable WAL mode for better concurrency
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")

        self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS machines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT UNIQUE NOT NULL,
                platform TEXT NOT NULL,
                created_at TEXT NOT NULL,
                last_seen TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                machine_id INTEGER NOT NULL,
                token_hash TEXT UNIQUE NOT NULL,
                created_at TEXT NOT NULL,
                expires_at TEXT,
                revoked INTEGER DEFAULT 0,
                FOREIGN KEY (machine_id) REFERENCES machines(id) ON DELETE CASCADE
            );

            CREATE TABLE IF NOT EXISTS files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                path TEXT UNIQUE NOT NULL,
                size INTEGER NOT NULL,
                content_hash TEXT NOT NULL,
                version INTEGER DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                updated_by INTEGER NOT NULL,
                deleted_at TEXT,
                FOREIGN KEY (updated_by) REFERENCES machines(id)
            );

            CREATE TABLE IF NOT EXISTS chunks (
                file_id INTEGER NOT NULL,
                chunk_index INTEGER NOT NULL,
                chunk_hash TEXT NOT NULL,
                PRIMARY KEY (file_id, chunk_index),
                FOREIGN KEY (file_id) REFERENCES files(id) ON DELETE CASCADE
            );

            CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);
            CREATE INDEX IF NOT EXISTS idx_files_deleted ON files(deleted_at);
            CREATE INDEX IF NOT EXISTS idx_tokens_hash ON tokens(token_hash);
        """)
        self._conn.commit()

    def close(self) -> None:
        """Close the database connection."""
        self._conn.close()

    # === Machine operations ===

    def create_machine(self, name: str, platform: str) -> Machine:
        """Register a new machine.

        Args:
            name: Unique machine name.
            platform: Operating system (Windows, Linux, macOS).

        Returns:
            Created Machine object.

        Raises:
            sqlite3.IntegrityError: If name already exists.
        """
        now = datetime.now(UTC).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO machines (name, platform, created_at, last_seen)
            VALUES (?, ?, ?, ?)
            """,
            (name, platform, now, now),
        )
        self._conn.commit()
        return Machine(
            id=cursor.lastrowid or 0,
            name=name,
            platform=platform,
            created_at=datetime.fromisoformat(now),
            last_seen=datetime.fromisoformat(now),
        )

    def get_machine(self, machine_id: int) -> Machine | None:
        """Get a machine by ID.

        Args:
            machine_id: Machine ID.

        Returns:
            Machine if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM machines WHERE id = ?",
            (machine_id,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_machine(row)

    def get_machine_by_name(self, name: str) -> Machine | None:
        """Get a machine by name.

        Args:
            name: Machine name.

        Returns:
            Machine if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM machines WHERE name = ?",
            (name,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_machine(row)

    def list_machines(self) -> list[Machine]:
        """List all registered machines.

        Returns:
            List of all machines.
        """
        cursor = self._conn.execute("SELECT * FROM machines ORDER BY name")
        return [self._row_to_machine(row) for row in cursor.fetchall()]

    def update_machine_last_seen(self, machine_id: int) -> None:
        """Update machine's last_seen timestamp.

        Args:
            machine_id: Machine ID.
        """
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE machines SET last_seen = ? WHERE id = ?",
            (now, machine_id),
        )
        self._conn.commit()

    def _row_to_machine(self, row: sqlite3.Row) -> Machine:
        """Convert database row to Machine object."""
        return Machine(
            id=row["id"],
            name=row["name"],
            platform=row["platform"],
            created_at=datetime.fromisoformat(row["created_at"]),
            last_seen=datetime.fromisoformat(row["last_seen"]),
        )

    # === Token operations ===

    def create_token(
        self,
        machine_id: int,
        expires_in: timedelta | None = None,
    ) -> tuple[str, Token]:
        """Create a new authentication token.

        Args:
            machine_id: Machine ID to associate with token.
            expires_in: Optional expiration duration.

        Returns:
            Tuple of (raw_token, Token object).
        """
        raw_token = "sa_" + secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)
        now = datetime.now(UTC)
        expires_at = (now + expires_in) if expires_in else None

        cursor = self._conn.execute(
            """
            INSERT INTO tokens (machine_id, token_hash, created_at, expires_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                machine_id,
                token_hash,
                now.isoformat(),
                expires_at.isoformat() if expires_at else None,
            ),
        )
        self._conn.commit()

        return raw_token, Token(
            id=cursor.lastrowid or 0,
            machine_id=machine_id,
            token_hash=token_hash,
            created_at=now,
            expires_at=expires_at,
            revoked=False,
        )

    def validate_token(self, raw_token: str) -> Token | None:
        """Validate a token and return it if valid.

        Args:
            raw_token: Raw token string.

        Returns:
            Token if valid, None otherwise.
        """
        token_hash = hash_token(raw_token)
        cursor = self._conn.execute(
            """
            SELECT * FROM tokens
            WHERE token_hash = ? AND revoked = 0
            """,
            (token_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None

        token = self._row_to_token(row)

        # Check expiration
        if token.expires_at and token.expires_at < datetime.now(UTC):
            return None

        return token

    def revoke_token(self, token_id: int) -> None:
        """Revoke a token.

        Args:
            token_id: Token ID to revoke.
        """
        self._conn.execute(
            "UPDATE tokens SET revoked = 1 WHERE id = ?",
            (token_id,),
        )
        self._conn.commit()

    def _row_to_token(self, row: sqlite3.Row) -> Token:
        """Convert database row to Token object."""
        return Token(
            id=row["id"],
            machine_id=row["machine_id"],
            token_hash=row["token_hash"],
            created_at=datetime.fromisoformat(row["created_at"]),
            expires_at=datetime.fromisoformat(row["expires_at"]) if row["expires_at"] else None,
            revoked=bool(row["revoked"]),
        )

    # === File operations ===

    def create_file(
        self,
        path: str,
        size: int,
        content_hash: str,
        machine_id: int,
    ) -> FileMetadata:
        """Create file metadata.

        Args:
            path: File path.
            size: File size in bytes.
            content_hash: Hash of file content.
            machine_id: ID of machine creating the file.

        Returns:
            Created FileMetadata object.
        """
        now = datetime.now(UTC).isoformat()
        cursor = self._conn.execute(
            """
            INSERT INTO files (path, size, content_hash, version, created_at, updated_at, updated_by)
            VALUES (?, ?, ?, 1, ?, ?, ?)
            """,
            (path, size, content_hash, now, now, machine_id),
        )
        self._conn.commit()

        return FileMetadata(
            id=cursor.lastrowid or 0,
            path=path,
            size=size,
            content_hash=content_hash,
            version=1,
            created_at=datetime.fromisoformat(now),
            updated_at=datetime.fromisoformat(now),
            updated_by=machine_id,
            deleted_at=None,
        )

    def get_file(self, path: str) -> FileMetadata | None:
        """Get file metadata by path.

        Args:
            path: File path.

        Returns:
            FileMetadata if found, None otherwise.
        """
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE path = ?",
            (path,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return self._row_to_file(row)

    def update_file(
        self,
        path: str,
        size: int,
        content_hash: str,
        machine_id: int,
        parent_version: int,
    ) -> FileMetadata:
        """Update file metadata with conflict detection.

        Args:
            path: File path.
            size: New file size.
            content_hash: New content hash.
            machine_id: ID of machine updating.
            parent_version: Expected current version (for conflict detection).

        Returns:
            Updated FileMetadata.

        Raises:
            ConflictError: If parent_version doesn't match current version.
        """
        # Check for conflicts
        current = self.get_file(path)
        if current is None:
            raise ValueError(f"File not found: {path}")

        if current.version != parent_version:
            raise ConflictError(
                f"Conflict detected: expected version {parent_version}, "
                f"but current version is {current.version}"
            )

        now = datetime.now(UTC).isoformat()
        new_version = current.version + 1

        self._conn.execute(
            """
            UPDATE files
            SET size = ?, content_hash = ?, version = ?, updated_at = ?, updated_by = ?
            WHERE path = ?
            """,
            (size, content_hash, new_version, now, machine_id, path),
        )
        self._conn.commit()

        return FileMetadata(
            id=current.id,
            path=path,
            size=size,
            content_hash=content_hash,
            version=new_version,
            created_at=current.created_at,
            updated_at=datetime.fromisoformat(now),
            updated_by=machine_id,
            deleted_at=None,
        )

    def list_files(self, prefix: str | None = None) -> list[FileMetadata]:
        """List files (excluding deleted).

        Args:
            prefix: Optional path prefix filter.

        Returns:
            List of file metadata.
        """
        if prefix:
            cursor = self._conn.execute(
                """
                SELECT * FROM files
                WHERE deleted_at IS NULL AND path LIKE ?
                ORDER BY path
                """,
                (prefix + "%",),
            )
        else:
            cursor = self._conn.execute(
                "SELECT * FROM files WHERE deleted_at IS NULL ORDER BY path"
            )
        return [self._row_to_file(row) for row in cursor.fetchall()]

    def delete_file(self, path: str, machine_id: int) -> None:
        """Soft-delete a file (move to trash).

        Args:
            path: File path.
            machine_id: ID of machine deleting.
        """
        now = datetime.now(UTC).isoformat()
        self._conn.execute(
            "UPDATE files SET deleted_at = ?, updated_by = ? WHERE path = ?",
            (now, machine_id, path),
        )
        self._conn.commit()

    def list_trash(self) -> list[FileMetadata]:
        """List deleted files.

        Returns:
            List of deleted file metadata.
        """
        cursor = self._conn.execute(
            "SELECT * FROM files WHERE deleted_at IS NOT NULL ORDER BY deleted_at DESC"
        )
        return [self._row_to_file(row) for row in cursor.fetchall()]

    def restore_file(self, path: str) -> None:
        """Restore a file from trash.

        Args:
            path: File path.
        """
        self._conn.execute(
            "UPDATE files SET deleted_at = NULL WHERE path = ?",
            (path,),
        )
        self._conn.commit()

    def purge_trash(self, older_than_days: int = 30) -> int:
        """Permanently delete old trash items.

        Args:
            older_than_days: Delete items older than this many days.

        Returns:
            Number of items purged.
        """
        cutoff = (datetime.now(UTC) - timedelta(days=older_than_days)).isoformat()
        cursor = self._conn.execute(
            "DELETE FROM files WHERE deleted_at IS NOT NULL AND deleted_at < ?",
            (cutoff,),
        )
        self._conn.commit()
        return cursor.rowcount

    def _row_to_file(self, row: sqlite3.Row) -> FileMetadata:
        """Convert database row to FileMetadata object."""
        return FileMetadata(
            id=row["id"],
            path=row["path"],
            size=row["size"],
            content_hash=row["content_hash"],
            version=row["version"],
            created_at=datetime.fromisoformat(row["created_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            updated_by=row["updated_by"],
            deleted_at=datetime.fromisoformat(row["deleted_at"]) if row["deleted_at"] else None,
        )

    # === Chunk operations ===

    def set_file_chunks(self, path: str, chunk_hashes: list[str]) -> None:
        """Set chunks for a file.

        Args:
            path: File path.
            chunk_hashes: Ordered list of chunk hashes.
        """
        file = self.get_file(path)
        if file is None:
            raise ValueError(f"File not found: {path}")

        # Delete existing chunks
        self._conn.execute("DELETE FROM chunks WHERE file_id = ?", (file.id,))

        # Insert new chunks
        for i, chunk_hash in enumerate(chunk_hashes):
            self._conn.execute(
                "INSERT INTO chunks (file_id, chunk_index, chunk_hash) VALUES (?, ?, ?)",
                (file.id, i, chunk_hash),
            )
        self._conn.commit()

    def get_file_chunks(self, path: str) -> list[str]:
        """Get chunks for a file.

        Args:
            path: File path.

        Returns:
            Ordered list of chunk hashes.
        """
        file = self.get_file(path)
        if file is None:
            return []

        cursor = self._conn.execute(
            """
            SELECT chunk_hash FROM chunks
            WHERE file_id = ?
            ORDER BY chunk_index
            """,
            (file.id,),
        )
        return [row["chunk_hash"] for row in cursor.fetchall()]
