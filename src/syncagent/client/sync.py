"""Sync operations for file upload and download.

This module provides:
- FileUploader: Upload files with chunking and encryption
- FileDownloader: Download files with decryption and assembly
- SyncEngine: Coordinate push/pull synchronization
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.api import ConflictError, NotFoundError, SyncClient
from syncagent.client.state import FileStatus, SyncState
from syncagent.core.chunking import Chunk, chunk_file
from syncagent.core.crypto import decrypt_chunk, encrypt_chunk

if TYPE_CHECKING:
    from syncagent.client.api import ServerFile

logger = logging.getLogger(__name__)


class SyncError(Exception):
    """Base exception for sync errors."""


class UploadError(SyncError):
    """Failed to upload a file."""


class DownloadError(SyncError):
    """Failed to download a file."""


@dataclass
class UploadResult:
    """Result of a file upload operation."""

    path: str
    server_file_id: int
    server_version: int
    chunk_hashes: list[str]
    size: int
    content_hash: str


@dataclass
class DownloadResult:
    """Result of a file download operation."""

    path: str
    local_path: Path
    size: int
    version: int


class FileUploader:
    """Handles file upload with chunking and encryption."""

    def __init__(
        self,
        client: SyncClient,
        encryption_key: bytes,
    ) -> None:
        """Initialize the uploader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for encryption.
        """
        self._client = client
        self._key = encryption_key

    def upload_file(
        self,
        local_path: Path,
        relative_path: str,
        parent_version: int | None = None,
    ) -> UploadResult:
        """Upload a file to the server.

        Args:
            local_path: Absolute path to the local file.
            relative_path: Relative path for storage on server.
            parent_version: Expected current version for updates (None for new files).

        Returns:
            UploadResult with server metadata.

        Raises:
            UploadError: If upload fails.
            ConflictError: If version conflict detected.
        """
        if not local_path.exists():
            raise UploadError(f"File not found: {local_path}")

        logger.info(f"Uploading {relative_path}")

        # Chunk the file
        chunks = list(chunk_file(local_path))
        chunk_hashes = [c.hash for c in chunks]

        # Calculate file hash
        content_hash = self._compute_file_hash(local_path)
        size = local_path.stat().st_size

        # Upload chunks that don't exist on server
        for chunk in chunks:
            self._upload_chunk_if_needed(chunk)

        # Create or update file metadata
        if parent_version is None:
            # New file
            server_file = self._client.create_file(
                path=relative_path,
                size=size,
                content_hash=content_hash,
                chunks=chunk_hashes,
            )
        else:
            # Update existing file
            server_file = self._client.update_file(
                path=relative_path,
                size=size,
                content_hash=content_hash,
                parent_version=parent_version,
                chunks=chunk_hashes,
            )

        logger.info(
            f"Uploaded {relative_path}: {len(chunks)} chunks, "
            f"version {server_file.version}"
        )

        return UploadResult(
            path=relative_path,
            server_file_id=server_file.id,
            server_version=server_file.version,
            chunk_hashes=chunk_hashes,
            size=size,
            content_hash=content_hash,
        )

    def _upload_chunk_if_needed(self, chunk: Chunk) -> None:
        """Upload a chunk only if it doesn't exist on server."""
        if self._client.chunk_exists(chunk.hash):
            logger.debug(f"Chunk {chunk.hash[:8]}... already exists")
            return

        encrypted = encrypt_chunk(chunk.data, self._key)
        self._client.upload_chunk(chunk.hash, encrypted)
        logger.debug(f"Uploaded chunk {chunk.hash[:8]}...")

    def _compute_file_hash(self, path: Path) -> str:
        """Compute SHA-256 hash of entire file."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                hasher.update(block)
        return hasher.hexdigest()


class FileDownloader:
    """Handles file download with decryption and assembly."""

    def __init__(
        self,
        client: SyncClient,
        encryption_key: bytes,
    ) -> None:
        """Initialize the downloader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for decryption.
        """
        self._client = client
        self._key = encryption_key

    def download_file(
        self,
        server_file: ServerFile,
        local_path: Path,
    ) -> DownloadResult:
        """Download a file from the server.

        Args:
            server_file: File metadata from server.
            local_path: Absolute path where to save the file.

        Returns:
            DownloadResult with local metadata.

        Raises:
            DownloadError: If download fails.
        """
        logger.info(f"Downloading {server_file.path}")

        # Get chunk hashes
        chunk_hashes = self._client.get_file_chunks(server_file.path)

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Download and assemble chunks
        with open(local_path, "wb") as f:
            for i, chunk_hash in enumerate(chunk_hashes):
                try:
                    encrypted = self._client.download_chunk(chunk_hash)
                    decrypted = decrypt_chunk(encrypted, self._key)
                    f.write(decrypted)
                    logger.debug(
                        f"Downloaded chunk {i + 1}/{len(chunk_hashes)}: "
                        f"{chunk_hash[:8]}..."
                    )
                except NotFoundError as e:
                    raise DownloadError(
                        f"Chunk {chunk_hash} not found for {server_file.path}"
                    ) from e
                except Exception as e:
                    raise DownloadError(
                        f"Failed to download chunk {chunk_hash}: {e}"
                    ) from e

        logger.info(
            f"Downloaded {server_file.path}: {len(chunk_hashes)} chunks, "
            f"version {server_file.version}"
        )

        return DownloadResult(
            path=server_file.path,
            local_path=local_path,
            size=server_file.size,
            version=server_file.version,
        )


@dataclass
class SyncResult:
    """Result of a sync operation."""

    uploaded: list[str]
    downloaded: list[str]
    conflicts: list[str]
    errors: list[str]


class SyncEngine:
    """Coordinates file synchronization between local and server."""

    def __init__(
        self,
        client: SyncClient,
        state: SyncState,
        base_path: Path,
        encryption_key: bytes,
    ) -> None:
        """Initialize the sync engine.

        Args:
            client: HTTP client for server communication.
            state: Local state database.
            base_path: Base directory for synced files.
            encryption_key: 32-byte AES key for encryption.
        """
        self._client = client
        self._state = state
        self._base_path = Path(base_path).resolve()
        self._key = encryption_key
        self._uploader = FileUploader(client, encryption_key)
        self._downloader = FileDownloader(client, encryption_key)

    def sync(self) -> SyncResult:
        """Perform a full sync operation.

        Returns:
            SyncResult with lists of uploaded, downloaded, and conflict files.
        """
        uploaded: list[str] = []
        downloaded: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []

        # 1. Push local changes to server
        push_result = self._push_changes()
        uploaded.extend(push_result["uploaded"])
        conflicts.extend(push_result["conflicts"])
        errors.extend(push_result["errors"])

        # 2. Pull remote changes from server
        pull_result = self._pull_changes()
        downloaded.extend(pull_result["downloaded"])
        errors.extend(pull_result["errors"])

        return SyncResult(
            uploaded=uploaded,
            downloaded=downloaded,
            conflicts=conflicts,
            errors=errors,
        )

    def push_file(self, relative_path: str) -> UploadResult | None:
        """Push a single file to the server.

        Args:
            relative_path: Relative path of the file.

        Returns:
            UploadResult if successful, None if conflict.
        """
        local_path = self._base_path / relative_path
        local_file = self._state.get_file(relative_path)

        parent_version = None
        if local_file and local_file.server_version:
            parent_version = local_file.server_version

        try:
            result = self._uploader.upload_file(
                local_path=local_path,
                relative_path=relative_path,
                parent_version=parent_version,
            )

            # Update local state
            if local_file:
                self._state.mark_synced(
                    relative_path,
                    server_file_id=result.server_file_id,
                    server_version=result.server_version,
                    chunk_hashes=result.chunk_hashes,
                )
            else:
                self._state.add_file(
                    relative_path,
                    local_mtime=local_path.stat().st_mtime,
                    local_size=result.size,
                    local_hash=result.content_hash,
                    status=FileStatus.SYNCED,
                )
                self._state.mark_synced(
                    relative_path,
                    server_file_id=result.server_file_id,
                    server_version=result.server_version,
                    chunk_hashes=result.chunk_hashes,
                )

            return result

        except ConflictError:
            logger.warning(f"Conflict detected for {relative_path}")
            self._state.mark_conflict(relative_path)
            return None

    def pull_file(self, server_file: ServerFile) -> DownloadResult:
        """Pull a single file from the server.

        Args:
            server_file: File metadata from server.

        Returns:
            DownloadResult with local metadata.
        """
        local_path = self._base_path / server_file.path

        result = self._downloader.download_file(
            server_file=server_file,
            local_path=local_path,
        )

        # Update local state
        local_file = self._state.get_file(server_file.path)
        if local_file:
            self._state.mark_synced(
                server_file.path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(server_file.path),
            )
        else:
            self._state.add_file(
                server_file.path,
                local_mtime=local_path.stat().st_mtime,
                local_size=server_file.size,
                local_hash=server_file.content_hash,
                status=FileStatus.SYNCED,
            )
            self._state.mark_synced(
                server_file.path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(server_file.path),
            )

        return result

    def _push_changes(self) -> dict[str, list[str]]:
        """Push local changes to server.

        Returns:
            Dict with uploaded, conflicts, and errors lists.
        """
        uploaded: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []

        # Get files that need uploading
        pending = self._state.get_pending_uploads()
        modified = self._state.list_files(status=FileStatus.MODIFIED)
        new_files = self._state.list_files(status=FileStatus.NEW)

        paths_to_push = set()
        for p in pending:
            paths_to_push.add(p.path)
        for f in modified:
            paths_to_push.add(f.path)
        for f in new_files:
            paths_to_push.add(f.path)

        for path in paths_to_push:
            try:
                result = self.push_file(path)
                if result:
                    uploaded.append(path)
                    self._state.remove_pending_upload(path)
                else:
                    conflicts.append(path)
            except Exception as e:
                logger.error(f"Failed to push {path}: {e}")
                errors.append(f"{path}: {e}")
                self._state.mark_upload_attempt(path, error=str(e))

        return {"uploaded": uploaded, "conflicts": conflicts, "errors": errors}

    def _pull_changes(self) -> dict[str, list[str]]:
        """Pull remote changes from server.

        Returns:
            Dict with downloaded and errors lists.
        """
        downloaded: list[str] = []
        errors: list[str] = []

        # Get all server files
        server_files = self._client.list_files()

        for server_file in server_files:
            local_file = self._state.get_file(server_file.path)

            # Skip if local is already up to date
            if local_file and local_file.server_version == server_file.version:
                continue

            # Skip if local has unsynced changes
            if local_file and local_file.status in (
                FileStatus.MODIFIED,
                FileStatus.NEW,
                FileStatus.CONFLICT,
            ):
                logger.debug(
                    f"Skipping pull for {server_file.path}: local changes pending"
                )
                continue

            try:
                self.pull_file(server_file)
                downloaded.append(server_file.path)
            except Exception as e:
                logger.error(f"Failed to pull {server_file.path}: {e}")
                errors.append(f"{server_file.path}: {e}")

        return {"downloaded": downloaded, "errors": errors}
