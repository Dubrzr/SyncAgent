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
from sqlalchemy.orm import Session, joinedload

from syncagent.server.models import (
    Admin,
    Base,
    ChangeLog,
    Chunk,
    FileMetadata,
    Invitation,
    Machine,
    Token,
)
from syncagent.server.models import Session as SessionModel

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


# Reserved machine name for server/admin operations
SERVER_MACHINE_NAME = "server"


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

    def get_or_create_server_machine(self) -> Machine:
        """Get or create the reserved 'server' machine for admin operations.

        This machine is used for operations performed by the server/admin
        (e.g., deleting files from web UI) rather than by a client.

        Returns:
            The server machine.
        """
        machine = self.get_machine_by_name(SERVER_MACHINE_NAME)
        if machine:
            return machine

        # Create the server machine
        with self._session() as session:
            machine = Machine(name=SERVER_MACHINE_NAME, platform="server")
            session.add(machine)
            session.commit()
            session.refresh(machine)
            session.expunge(machine)
            return machine

    def delete_machine(self, machine_id: int) -> bool:
        """Delete a machine and its associated data.

        This will:
        - Delete all tokens for this machine
        - Delete invitations used by this machine (invitations are one-time use)
        - Delete files uploaded by this machine

        Args:
            machine_id: Machine ID.

        Returns:
            True if machine was deleted, False if not found.
        """
        with self._session() as session:
            machine = session.get(Machine, machine_id)
            if not machine:
                return False

            # Delete associated tokens first (cascade should handle this, but be explicit)
            token_stmt = select(Token).where(Token.machine_id == machine_id)
            tokens = list(session.execute(token_stmt).scalars().all())
            for token in tokens:
                session.delete(token)

            # Delete invitations that were used by this machine (one-time use)
            inv_stmt = select(Invitation).where(Invitation.used_by_machine_id == machine_id)
            invitations = list(session.execute(inv_stmt).scalars().all())
            for invitation in invitations:
                session.delete(invitation)

            # Clear file references to this machine (set to a sentinel or handle differently)
            # For now, we'll delete files that were created by this machine
            file_stmt = select(FileMetadata).where(FileMetadata.updated_by == machine_id)
            files = list(session.execute(file_stmt).scalars().all())
            for file in files:
                session.delete(file)

            # Delete the machine
            session.delete(machine)
            session.commit()
            return True

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
            session.flush()  # Get file.id before commit

            # Log change
            change = ChangeLog(
                file_id=file.id,
                file_path=path,
                action="CREATED",
                version=file.version,
                machine_id=machine_id,
            )
            session.add(change)

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

            # Log change
            change = ChangeLog(
                file_id=file.id,
                file_path=path,
                action="UPDATED",
                version=file.version,
                machine_id=machine_id,
            )
            session.add(change)

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

    def delete_file(self, path: str, machine_id: int | None) -> int:
        """Soft-delete a file or folder (move to trash).

        If the exact path matches a file, deletes that file.
        If not found, treats the path as a folder and deletes all files inside.

        Args:
            path: File or folder path.
            machine_id: ID of machine deleting (None uses 'server' machine).

        Returns:
            Number of files deleted.
        """
        # Use server machine for admin deletions
        actual_machine_id = machine_id
        if actual_machine_id is None:
            server_machine = self.get_or_create_server_machine()
            actual_machine_id = server_machine.id

        with self._session() as session:
            # Try exact file match first
            stmt = select(FileMetadata).where(
                FileMetadata.path == path,
                FileMetadata.deleted_at.is_(None),
            )
            file = session.execute(stmt).scalar_one_or_none()

            if file:
                # Single file deletion
                file.deleted_at = datetime.now(UTC)
                file.version += 1

                if machine_id is not None:
                    file.updated_by = machine_id

                change = ChangeLog(
                    file_id=file.id,
                    file_path=path,
                    action="DELETED",
                    version=file.version,
                    machine_id=actual_machine_id,
                )
                session.add(change)
                session.commit()
                return 1

            # No exact match - try as folder prefix
            folder_path = path if path.endswith("/") else path + "/"
            stmt = select(FileMetadata).where(
                FileMetadata.path.startswith(folder_path),
                FileMetadata.deleted_at.is_(None),
            )
            files = list(session.execute(stmt).scalars().all())

            if not files:
                return 0

            now = datetime.now(UTC)
            for f in files:
                f.deleted_at = now
                f.version += 1

                if machine_id is not None:
                    f.updated_by = machine_id

                change = ChangeLog(
                    file_id=f.id,
                    file_path=f.path,
                    action="DELETED",
                    version=f.version,
                    machine_id=actual_machine_id,
                )
                session.add(change)

            session.commit()
            return len(files)

    def delete_folder(self, folder_path: str, machine_id: int | None) -> int:
        """Soft-delete all files in a folder (recursive).

        Args:
            folder_path: Folder path (all files with this prefix will be deleted).
            machine_id: ID of machine deleting (None uses 'server' machine).

        Returns:
            Number of files deleted.
        """
        # Use server machine for admin deletions
        actual_machine_id = machine_id
        if actual_machine_id is None:
            server_machine = self.get_or_create_server_machine()
            actual_machine_id = server_machine.id

        # Ensure folder path ends with /
        if not folder_path.endswith("/"):
            folder_path = folder_path + "/"

        deleted_count = 0
        now = datetime.now(UTC)

        with self._session() as session:
            # Find all non-deleted files in the folder
            stmt = select(FileMetadata).where(
                FileMetadata.path.startswith(folder_path),
                FileMetadata.deleted_at.is_(None),
            )
            files = list(session.execute(stmt).scalars().all())

            for file in files:
                file.deleted_at = now
                file.version += 1

                # Update updated_by if original machine_id was provided
                if machine_id is not None:
                    file.updated_by = machine_id

                # Log change
                change = ChangeLog(
                    file_id=file.id,
                    file_path=file.path,
                    action="DELETED",
                    version=file.version,
                    machine_id=actual_machine_id,
                )
                session.add(change)
                deleted_count += 1

            session.commit()

        return deleted_count

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

    # Alias for web UI
    list_deleted_files = list_trash

    def restore_file(self, file_id: int) -> None:
        """Restore a file from trash.

        Args:
            file_id: File ID.
        """
        with self._session() as session:
            file = session.get(FileMetadata, file_id)
            if file:
                file.deleted_at = None
                session.commit()

    def restore_file_by_path(self, path: str) -> None:
        """Restore a file from trash by path.

        Args:
            path: File path.
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.path == path)
            file = session.execute(stmt).scalar_one_or_none()
            if file:
                file.deleted_at = None
                session.commit()

    def permanently_delete_file(self, file_id: int) -> list[str]:
        """Permanently delete a file.

        Args:
            file_id: File ID.

        Returns:
            List of chunk hashes that were associated with the file
            (caller should delete these from storage).
        """
        with self._session() as session:
            file = session.get(FileMetadata, file_id)
            if file:
                # Collect chunk hashes before deletion
                chunk_hashes = [chunk.chunk_hash for chunk in file.chunks]
                # Also delete associated chunks
                for chunk in list(file.chunks):
                    session.delete(chunk)
                session.delete(file)
                session.commit()
                return chunk_hashes
            return []

    def empty_trash(self) -> tuple[int, list[str]]:
        """Permanently delete all files in trash.

        Returns:
            Tuple of (number of files deleted, list of chunk hashes to delete from storage).
        """
        with self._session() as session:
            stmt = select(FileMetadata).where(FileMetadata.deleted_at.is_not(None))
            files = list(session.execute(stmt).scalars().all())
            count = len(files)
            chunk_hashes: list[str] = []
            for file in files:
                for chunk in list(file.chunks):
                    chunk_hashes.append(chunk.chunk_hash)
                    session.delete(chunk)
                session.delete(file)
            session.commit()
            return count, chunk_hashes

    def purge_trash(self, older_than_days: int = 30) -> tuple[int, list[str]]:
        """Permanently delete old trash items.

        Args:
            older_than_days: Delete items older than this many days.

        Returns:
            Tuple of (number of items purged, list of chunk hashes to delete from storage).
        """
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        with self._session() as session:
            stmt = select(FileMetadata).where(
                FileMetadata.deleted_at.is_not(None),
                FileMetadata.deleted_at < cutoff,
            )
            files = list(session.execute(stmt).scalars().all())
            count = len(files)
            chunk_hashes: list[str] = []
            for file in files:
                # Collect chunk hashes before deletion
                for chunk in list(file.chunks):
                    chunk_hashes.append(chunk.chunk_hash)
                    session.delete(chunk)
                session.delete(file)
            session.commit()
            return count, chunk_hashes

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

    # === Admin operations ===

    def needs_setup(self) -> bool:
        """Check if initial setup is required.

        Returns:
            True if no admin exists.
        """
        with self._session() as session:
            stmt = select(Admin).where(Admin.id == 1)
            admin = session.execute(stmt).scalar_one_or_none()
            return admin is None

    def create_admin(self, username: str, password_hash: str) -> Admin:
        """Create the admin user.

        Args:
            username: Admin username.
            password_hash: Argon2id hashed password.

        Returns:
            Created Admin object.

        Raises:
            ValueError: If admin already exists.
        """
        if not self.needs_setup():
            raise ValueError("Admin already exists")

        with self._session() as session:
            admin = Admin(id=1, username=username, password_hash=password_hash)
            session.add(admin)
            session.commit()
            session.refresh(admin)
            session.expunge(admin)
            return admin

    def get_admin(self) -> Admin | None:
        """Get the admin user.

        Returns:
            Admin if exists, None otherwise.
        """
        with self._session() as session:
            admin = session.get(Admin, 1)
            if admin:
                session.expunge(admin)
            return admin

    # === Session operations ===

    def create_session(
        self,
        expires_in: timedelta = timedelta(hours=24),
        user_agent: str | None = None,
        ip_address: str | None = None,
    ) -> tuple[str, SessionModel]:
        """Create a new admin session.

        Args:
            expires_in: Session expiration duration.
            user_agent: Client user agent.
            ip_address: Client IP address.

        Returns:
            Tuple of (raw_session_token, Session object).
        """
        raw_token = secrets.token_urlsafe(32)
        token_hash = hash_token(raw_token)
        now = datetime.now(UTC)
        expires_at = now + expires_in

        with self._session() as session:
            sess = SessionModel(
                token_hash=token_hash,
                created_at=now,
                expires_at=expires_at,
                user_agent=user_agent,
                ip_address=ip_address,
            )
            session.add(sess)
            session.commit()
            session.refresh(sess)
            session.expunge(sess)
            return raw_token, sess

    def validate_session(self, raw_token: str) -> SessionModel | None:
        """Validate a session token.

        Args:
            raw_token: Raw session token.

        Returns:
            Session if valid, None otherwise.
        """
        token_hash = hash_token(raw_token)
        with self._session() as session:
            stmt = select(SessionModel).where(SessionModel.token_hash == token_hash)
            sess = session.execute(stmt).scalar_one_or_none()

            if sess is None:
                return None

            # Check expiration
            now = datetime.now(UTC)
            expires_at = sess.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < now:
                return None

            session.expunge(sess)
            return sess

    def delete_session(self, raw_token: str) -> None:
        """Delete a session (logout).

        Args:
            raw_token: Raw session token.
        """
        token_hash = hash_token(raw_token)
        with self._session() as session:
            stmt = select(SessionModel).where(SessionModel.token_hash == token_hash)
            sess = session.execute(stmt).scalar_one_or_none()
            if sess:
                session.delete(sess)
                session.commit()

    def cleanup_expired_sessions(self) -> int:
        """Delete all expired sessions.

        Returns:
            Number of sessions deleted.
        """
        now = datetime.now(UTC)
        with self._session() as session:
            stmt = select(SessionModel).where(SessionModel.expires_at < now)
            sessions = list(session.execute(stmt).scalars().all())
            count = len(sessions)
            for sess in sessions:
                session.delete(sess)
            session.commit()
            return count

    # === Invitation operations ===

    def create_invitation(
        self,
        expires_in: timedelta = timedelta(hours=24),
    ) -> tuple[str, Invitation]:
        """Create a new machine invitation.

        Args:
            expires_in: Invitation expiration duration.

        Returns:
            Tuple of (raw_invitation_token, Invitation object).
        """
        raw_token = "INV-" + secrets.token_urlsafe(16)
        token_hash = hash_token(raw_token)
        now = datetime.now(UTC)
        expires_at = now + expires_in

        with self._session() as session:
            invitation = Invitation(
                token_hash=token_hash,
                created_at=now,
                expires_at=expires_at,
            )
            session.add(invitation)
            session.commit()
            session.refresh(invitation)
            session.expunge(invitation)
            return raw_token, invitation

    def validate_invitation(self, raw_token: str) -> Invitation | None:
        """Validate an invitation token.

        Args:
            raw_token: Raw invitation token.

        Returns:
            Invitation if valid (not used, not expired), None otherwise.
        """
        token_hash = hash_token(raw_token)
        with self._session() as session:
            stmt = select(Invitation).where(
                Invitation.token_hash == token_hash,
                Invitation.used_by_machine_id.is_(None),
            )
            invitation = session.execute(stmt).scalar_one_or_none()

            if invitation is None:
                return None

            # Check expiration
            now = datetime.now(UTC)
            expires_at = invitation.expires_at
            if expires_at.tzinfo is None:
                expires_at = expires_at.replace(tzinfo=UTC)
            if expires_at < now:
                return None

            session.expunge(invitation)
            return invitation

    def use_invitation(self, raw_token: str, machine_id: int) -> None:
        """Mark an invitation as used.

        Args:
            raw_token: Raw invitation token.
            machine_id: ID of machine that used it.
        """
        token_hash = hash_token(raw_token)
        with self._session() as session:
            stmt = select(Invitation).where(Invitation.token_hash == token_hash)
            invitation = session.execute(stmt).scalar_one_or_none()
            if invitation:
                invitation.used_by_machine_id = machine_id
                invitation.used_at = datetime.now(UTC)
                session.commit()

    def list_invitations(self) -> list[Invitation]:
        """List all invitations.

        Returns:
            List of all invitations.
        """
        with self._session() as session:
            stmt = (
                select(Invitation)
                .options(joinedload(Invitation.used_by_machine))
                .order_by(Invitation.created_at.desc())
            )
            invitations = list(session.execute(stmt).scalars().unique().all())
            for inv in invitations:
                session.expunge(inv)
            return invitations

    def delete_invitation(self, invitation_id: int) -> None:
        """Delete an invitation.

        Args:
            invitation_id: Invitation ID.
        """
        with self._session() as session:
            invitation = session.get(Invitation, invitation_id)
            if invitation:
                session.delete(invitation)
                session.commit()

    def cleanup_expired_invitations(self) -> int:
        """Delete all expired unused invitations.

        Returns:
            Number of invitations deleted.
        """
        now = datetime.now(UTC)
        with self._session() as session:
            stmt = select(Invitation).where(
                Invitation.expires_at < now,
                Invitation.used_by_machine_id.is_(None),
            )
            invitations = list(session.execute(stmt).scalars().all())
            count = len(invitations)
            for inv in invitations:
                session.delete(inv)
            session.commit()
            return count

    # === Statistics operations ===

    def get_machine_stats(self, machine_id: int) -> dict[str, int]:
        """Get statistics for a machine.

        Args:
            machine_id: Machine ID.

        Returns:
            Dict with file_count and total_size.
        """
        with self._session() as session:
            from sqlalchemy import func

            # Count files updated by this machine (not deleted)
            count_stmt = (
                select(func.count(FileMetadata.id))
                .where(
                    FileMetadata.updated_by == machine_id,
                    FileMetadata.deleted_at.is_(None),
                )
            )
            file_count = session.execute(count_stmt).scalar() or 0

            # Sum sizes of files updated by this machine
            size_stmt = (
                select(func.coalesce(func.sum(FileMetadata.size), 0))
                .where(
                    FileMetadata.updated_by == machine_id,
                    FileMetadata.deleted_at.is_(None),
                )
            )
            total_size = session.execute(size_stmt).scalar() or 0

            return {"file_count": file_count, "total_size": total_size}

    def get_all_machines_stats(self) -> dict[int, dict[str, int]]:
        """Get statistics for all machines.

        Returns:
            Dict mapping machine_id to stats dict.
        """
        with self._session() as session:
            from sqlalchemy import func

            # Get file counts and sizes grouped by machine
            stmt = (
                select(
                    FileMetadata.updated_by,
                    func.count(FileMetadata.id).label("file_count"),
                    func.coalesce(func.sum(FileMetadata.size), 0).label("total_size"),
                )
                .where(FileMetadata.deleted_at.is_(None))
                .group_by(FileMetadata.updated_by)
            )
            results = session.execute(stmt).all()

            stats: dict[int, dict[str, int]] = {}
            for row in results:
                stats[row.updated_by] = {
                    "file_count": row.file_count,
                    "total_size": row.total_size,
                }
            return stats

    # === Change log operations ===

    def get_changes_since(
        self,
        since: datetime,
        limit: int = 1000,
    ) -> list[ChangeLog]:
        """Get changes since a given timestamp.

        This is used for incremental sync - clients poll this endpoint
        to get only the changes since their last sync.

        Args:
            since: Get changes after this timestamp.
            limit: Maximum number of changes to return.

        Returns:
            List of ChangeLog entries ordered by timestamp.
        """
        with self._session() as session:
            stmt = (
                select(ChangeLog)
                .where(ChangeLog.timestamp > since)
                .order_by(ChangeLog.timestamp.asc())
                .limit(limit)
            )
            changes = list(session.execute(stmt).scalars().all())
            for change in changes:
                session.expunge(change)
            return changes

    def get_latest_change_timestamp(self) -> datetime | None:
        """Get the timestamp of the most recent change.

        Returns:
            Timestamp of most recent change, or None if no changes exist.
        """
        with self._session() as session:
            from sqlalchemy import func

            stmt = select(func.max(ChangeLog.timestamp))
            result = session.execute(stmt).scalar()
            return result

    def cleanup_old_changes(self, older_than_days: int = 30) -> int:
        """Delete old change log entries.

        Args:
            older_than_days: Delete entries older than this many days.

        Returns:
            Number of entries deleted.
        """
        cutoff = datetime.now(UTC) - timedelta(days=older_than_days)
        with self._session() as session:
            stmt = select(ChangeLog).where(ChangeLog.timestamp < cutoff)
            changes = list(session.execute(stmt).scalars().all())
            count = len(changes)
            for change in changes:
                session.delete(change)
            session.commit()
            return count
