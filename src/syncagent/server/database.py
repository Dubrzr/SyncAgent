"""Server database using SQLAlchemy with SQLite.

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
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session

from syncagent.server.models import Base, Chunk, FileMetadata, Machine, Token

if TYPE_CHECKING:
    from sqlalchemy import Engine


def hash_token(token: str) -> str:
    """Hash a token using SHA-256.

    Args:
        token: Raw token string.

    Returns:
        Hex-encoded SHA-256 hash.
    """
    return hashlib.sha256(token.encode()).hexdigest()


class ConflictError(Exception):
    """Raised when a conflict is detected during file update."""


class Database:
    """SQLAlchemy database for server metadata.

    Uses SQLite with WAL mode for better concurrency with multiple readers.
    """

    def __init__(self, db_path: Path) -> None:
        """Initialize the database.

        Args:
            db_path: Path to the SQLite database file.
        """
        self._db_path = Path(db_path)
        self._db_path.parent.mkdir(parents=True, exist_ok=True)

        # Create engine with check_same_thread=False for multi-threaded access
        self._engine: Engine = create_engine(
            f"sqlite:///{self._db_path}",
            connect_args={"check_same_thread": False},
            echo=False,
        )

        # Enable WAL mode
        with self._engine.connect() as conn:
            conn.exec_driver_sql("PRAGMA journal_mode=WAL")
            conn.exec_driver_sql("PRAGMA foreign_keys=ON")

        # Create tables if they don't exist
        Base.metadata.create_all(self._engine)

    def close(self) -> None:
        """Close the database connection."""
        self._engine.dispose()

    def _session(self) -> Session:
        """Create a new database session."""
        return Session(self._engine)

    # === Machine operations ===

    def create_machine(self, name: str, platform: str) -> Machine:
        """Register a new machine.

        Args:
            name: Unique machine name.
            platform: Operating system (Windows, Linux, macOS).

        Returns:
            Created Machine object.

        Raises:
            IntegrityError: If name already exists.
        """
        with self._session() as session:
            machine = Machine(name=name, platform=platform)
            session.add(machine)
            session.commit()
            session.refresh(machine)
            # Expunge to detach from session
            session.expunge(machine)
            return machine

    def get_machine(self, machine_id: int) -> Machine | None:
        """Get a machine by ID.

        Args:
            machine_id: Machine ID.

        Returns:
            Machine if found, None otherwise.
        """
        with self._session() as session:
            machine = session.get(Machine, machine_id)
            if machine:
                session.expunge(machine)
            return machine

    def get_machine_by_name(self, name: str) -> Machine | None:
        """Get a machine by name.

        Args:
            name: Machine name.

        Returns:
            Machine if found, None otherwise.
        """
        with self._session() as session:
            stmt = select(Machine).where(Machine.name == name)
            machine = session.execute(stmt).scalar_one_or_none()
            if machine:
                session.expunge(machine)
            return machine

    def list_machines(self) -> list[Machine]:
        """List all registered machines.

        Returns:
            List of all machines.
        """
        with self._session() as session:
            stmt = select(Machine).order_by(Machine.name)
            machines = list(session.execute(stmt).scalars().all())
            for machine in machines:
                session.expunge(machine)
            return machines

    def update_machine_last_seen(self, machine_id: int) -> None:
        """Update machine's last_seen timestamp.

        Args:
            machine_id: Machine ID.
        """
        with self._session() as session:
            machine = session.get(Machine, machine_id)
            if machine:
                machine.last_seen = datetime.now(UTC)
                session.commit()

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

        with self._session() as session:
            token = Token(
                machine_id=machine_id,
                token_hash=token_hash,
                created_at=now,
                expires_at=expires_at,
            )
            session.add(token)
            session.commit()
            session.refresh(token)
            session.expunge(token)
            return raw_token, token

    def validate_token(self, raw_token: str) -> Token | None:
        """Validate a token and return it if valid.

        Args:
            raw_token: Raw token string.

        Returns:
            Token if valid, None otherwise.
        """
        token_hash = hash_token(raw_token)
        with self._session() as session:
            stmt = select(Token).where(Token.token_hash == token_hash, Token.revoked == False)  # noqa: E712
            token = session.execute(stmt).scalar_one_or_none()

            if token is None:
                return None

            # Check expiration (handle both naive and aware datetimes)
            if token.expires_at:
                now = datetime.now(UTC)
                expires_at = token.expires_at
                # If expires_at is naive, assume UTC
                if expires_at.tzinfo is None:
                    expires_at = expires_at.replace(tzinfo=UTC)
                if expires_at < now:
                    return None

            session.expunge(token)
            return token

    def revoke_token(self, token_id: int) -> None:
        """Revoke a token.

        Args:
            token_id: Token ID to revoke.
        """
        with self._session() as session:
            token = session.get(Token, token_id)
            if token:
                token.revoked = True
                session.commit()

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
        with self._session() as session:
            file = FileMetadata(
                path=path,
                size=size,
                content_hash=content_hash,
                updated_by=machine_id,
            )
            session.add(file)
            session.commit()
            session.refresh(file)
            session.expunge(file)
            return file

    def get_file(self, path: str) -> FileMetadata | None:
        """Get file metadata by path.

        Args:
            path: File path.

        Returns:
            FileMetadata if found, None otherwise.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()
            if file:
                session.expunge(file)
            return file

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
            ValueError: If file not found.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()

            if file is None:
                raise ValueError(f"File not found: {path}")

            if file.version != parent_version:
                raise ConflictError(
                    f"Conflict detected: expected version {parent_version}, "
                    f"but current version is {file.version}"
                )

            file.size = size
            file.content_hash = content_hash
            file.version += 1
            file.updated_at = datetime.now(UTC)
            file.updated_by = machine_id

            session.commit()
            session.refresh(file)
            session.expunge(file)
            return file

    def list_files(self, prefix: str | None = None) -> list[FileMetadata]:
        """List files (excluding deleted).

        Args:
            prefix: Optional path prefix filter.

        Returns:
            List of file metadata.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.deleted_at.is_(None))
            if prefix:
                stmt = stmt.where(FileMetadata.path.startswith(prefix))
            stmt = stmt.order_by(FileMetadata.path)
            files = list(session.execute(stmt).scalars().all())
            for file in files:
                session.expunge(file)
            return files

    def delete_file(self, path: str, machine_id: int) -> None:
        """Soft-delete a file (move to trash).

        Args:
            path: File path.
            machine_id: ID of machine deleting.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()
            if file:
                file.deleted_at = datetime.now(UTC)
                file.updated_by = machine_id
                session.commit()

    def list_trash(self) -> list[FileMetadata]:
        """List deleted files.

        Returns:
            List of deleted file metadata.
        """
        with self._session() as session:
            stmt = (
                select(FileMetadata)
                .where(FileMetadata.deleted_at.is_not(None))
                .order_by(FileMetadata.deleted_at.desc())
            )
            files = list(session.execute(stmt).scalars().all())
            for file in files:
                session.expunge(file)
            return files

    def restore_file(self, path: str) -> None:
        """Restore a file from trash.

        Args:
            path: File path.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()
            if file:
                file.deleted_at = None
                session.commit()

    def purge_trash(self, older_than_days: int = 30) -> int:
        """Permanently delete old trash items.

        Args:
            older_than_days: Delete items older than this many days.

        Returns:
            Number of items purged.
        """
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        with self._session() as session:
            stmt = select(FileMetadata).where(
                FileMetadata.deleted_at.is_not(None),
                FileMetadata.deleted_at < cutoff,
            )
            files = list(session.execute(stmt).scalars().all())
            count = len(files)
            for file in files:
                session.delete(file)
            session.commit()
            return count

    # === Chunk operations ===

    def set_file_chunks(self, path: str, chunk_hashes: list[str]) -> None:
        """Set chunks for a file.

        Args:
            path: File path.
            chunk_hashes: Ordered list of chunk hashes.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()
            if file is None:
                raise ValueError(f"File not found: {path}")

            # Delete existing chunks
            for chunk in list(file.chunks):
                session.delete(chunk)

            # Insert new chunks
            for i, chunk_hash in enumerate(chunk_hashes):
                chunk = Chunk(file_id=file.id, chunk_index=i, chunk_hash=chunk_hash)
                session.add(chunk)

            session.commit()

    def get_file_chunks(self, path: str) -> list[str]:
        """Get chunks for a file.

        Args:
            path: File path.

        Returns:
            Ordered list of chunk hashes.
        """
        with self._session() as session:
            file_stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(file_stmt).scalar_one_or_none()
            if file is None:
                return []

            chunk_stmt = (
                select(Chunk)
                .where(Chunk.file_id == file.id)
                .order_by(Chunk.chunk_index)
            )
            chunks = session.execute(chunk_stmt).scalars().all()
            return [chunk.chunk_hash for chunk in chunks]
