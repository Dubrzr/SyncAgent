"""Sync operations for file upload and download.

This module provides:
- FileUploader: Upload files with chunking and encryption
- FileDownloader: Download files with decryption and assembly
- SyncEngine: Coordinate push/pull synchronization
- Conflict detection and resolution
"""

from __future__ import annotations

import contextlib
import hashlib
import logging
import os
import socket
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING, Any

from syncagent.client.api import ConflictError, NotFoundError, SyncClient
from syncagent.client.state import FileStatus, SyncState
from syncagent.core.chunking import Chunk, chunk_file
from syncagent.core.crypto import decrypt_chunk, encrypt_chunk

# Default retry configuration
DEFAULT_MAX_RETRIES = 5
DEFAULT_INITIAL_BACKOFF = 1.0  # seconds
DEFAULT_MAX_BACKOFF = 60.0  # seconds
DEFAULT_BACKOFF_MULTIPLIER = 2.0

if TYPE_CHECKING:
    from syncagent.client.api import ServerFile

logger = logging.getLogger(__name__)


def retry_with_backoff(
    func: Callable[[], Any],
    max_retries: int = DEFAULT_MAX_RETRIES,
    initial_backoff: float = DEFAULT_INITIAL_BACKOFF,
    max_backoff: float = DEFAULT_MAX_BACKOFF,
    backoff_multiplier: float = DEFAULT_BACKOFF_MULTIPLIER,
    retryable_exceptions: tuple[type[Exception], ...] = (Exception,),
) -> Any:
    """Execute a function with exponential backoff retry.

    Args:
        func: Function to execute.
        max_retries: Maximum number of retry attempts.
        initial_backoff: Initial backoff time in seconds.
        max_backoff: Maximum backoff time in seconds.
        backoff_multiplier: Multiplier for each retry.
        retryable_exceptions: Tuple of exception types to retry on.

    Returns:
        Result of the function.

    Raises:
        The last exception if all retries fail.
    """
    backoff = initial_backoff
    last_exception: Exception | None = None

    for attempt in range(max_retries + 1):
        try:
            return func()
        except retryable_exceptions as e:
            last_exception = e
            if attempt == max_retries:
                logger.error(f"All {max_retries} retries failed: {e}")
                raise

            logger.warning(
                f"Attempt {attempt + 1}/{max_retries + 1} failed: {e}. "
                f"Retrying in {backoff:.1f}s..."
            )
            time.sleep(backoff)
            backoff = min(backoff * backoff_multiplier, max_backoff)

    # Should not reach here, but satisfy type checker
    if last_exception:
        raise last_exception
    raise RuntimeError("Unexpected retry loop exit")


def get_machine_name() -> str:
    """Get the current machine name for conflict file naming."""
    return socket.gethostname()


def generate_conflict_filename(original_path: Path, machine_name: str | None = None) -> Path:
    """Generate a conflict filename with timestamp and machine name.

    Format: filename.conflict-YYYYMMDD-HHMMSS-{machine}.ext

    Args:
        original_path: Original file path.
        machine_name: Machine name (defaults to hostname).

    Returns:
        Path with conflict naming.
    """
    if machine_name is None:
        machine_name = get_machine_name()

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = original_path.stem
    suffix = original_path.suffix

    # Sanitize machine name (remove problematic characters)
    safe_machine = "".join(c if c.isalnum() or c in "-_" else "_" for c in machine_name)

    new_name = f"{stem}.conflict-{timestamp}-{safe_machine}{suffix}"
    return original_path.parent / new_name


class SyncError(Exception):
    """Base exception for sync errors."""


class UploadError(SyncError):
    """Failed to upload a file."""


class DownloadError(SyncError):
    """Failed to download a file."""


@dataclass
class SyncProgress:
    """Progress information for sync operations."""

    file_path: str
    file_size: int
    current_chunk: int
    total_chunks: int
    bytes_transferred: int
    operation: str  # "upload" or "download"

    @property
    def percent(self) -> float:
        """Get progress percentage."""
        if self.total_chunks == 0:
            return 100.0
        return (self.current_chunk / self.total_chunks) * 100


# Type alias for progress callback
ProgressCallback = Callable[[SyncProgress], None]


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
    """Handles file upload with chunking and encryption.

    Supports resumable uploads at chunk level for robustness against
    network interruptions.
    """

    def __init__(
        self,
        client: SyncClient,
        encryption_key: bytes,
        progress_callback: ProgressCallback | None = None,
        state: SyncState | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Initialize the uploader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for encryption.
            progress_callback: Optional callback for progress updates.
            state: Optional SyncState for tracking upload progress (enables resume).
            max_retries: Maximum retry attempts for chunk uploads.
        """
        self._client = client
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._state = state
        self._max_retries = max_retries

    def upload_file(
        self,
        local_path: Path,
        relative_path: str,
        parent_version: int | None = None,
    ) -> UploadResult:
        """Upload a file to the server with resumable chunk uploads.

        If state tracking is enabled, upload progress is saved after each
        chunk, allowing interrupted uploads to resume from where they left off.

        Args:
            local_path: Absolute path to the local file.
            relative_path: Relative path for storage on server.
            parent_version: Expected current version for updates (None for new files).

        Returns:
            UploadResult with server metadata.

        Raises:
            UploadError: If upload fails after all retries.
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

        # Check for existing upload progress (resume support)
        already_uploaded: set[str] = set()
        if self._state:
            progress = self._state.get_upload_progress(relative_path)
            if progress:
                # Verify chunk list matches (file hasn't changed)
                if progress.chunk_hashes == chunk_hashes:
                    already_uploaded = set(progress.uploaded_hashes)
                    logger.info(
                        f"Resuming upload: {len(already_uploaded)}/{len(chunks)} "
                        "chunks already uploaded"
                    )
                else:
                    # File changed, start fresh
                    logger.info("File changed since last upload attempt, starting fresh")
                    self._state.clear_upload_progress(relative_path)

            # Start tracking progress
            if not already_uploaded:
                self._state.start_upload_progress(relative_path, chunk_hashes)

        # Upload chunks that don't exist on server
        bytes_transferred = 0
        for i, chunk in enumerate(chunks):
            # Skip already uploaded chunks
            if chunk.hash in already_uploaded:
                bytes_transferred += len(chunk.data)
                logger.debug(f"Skipping already uploaded chunk {chunk.hash[:8]}...")
            else:
                self._upload_chunk_with_retry(chunk, relative_path)
                bytes_transferred += len(chunk.data)

            # Report progress
            if self._progress_callback:
                self._progress_callback(SyncProgress(
                    file_path=relative_path,
                    file_size=size,
                    current_chunk=i + 1,
                    total_chunks=len(chunks),
                    bytes_transferred=bytes_transferred,
                    operation="upload",
                ))

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

        # Clear upload progress on success
        if self._state:
            self._state.clear_upload_progress(relative_path)

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

    def _upload_chunk_with_retry(self, chunk: Chunk, relative_path: str) -> None:
        """Upload a chunk with retry and progress tracking.

        Args:
            chunk: Chunk to upload.
            relative_path: Path for progress tracking.
        """
        # Check if chunk already exists on server (deduplication)
        if self._client.chunk_exists(chunk.hash):
            logger.debug(f"Chunk {chunk.hash[:8]}... already exists on server")
            if self._state:
                self._state.mark_chunk_uploaded(relative_path, chunk.hash)
            return

        # Upload with retry
        encrypted = encrypt_chunk(chunk.data, self._key)

        def do_upload() -> None:
            self._client.upload_chunk(chunk.hash, encrypted)

        retry_with_backoff(
            func=do_upload,
            max_retries=self._max_retries,
            retryable_exceptions=(OSError, ConnectionError, TimeoutError),
        )

        # Track progress
        if self._state:
            self._state.mark_chunk_uploaded(relative_path, chunk.hash)

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
        progress_callback: ProgressCallback | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Initialize the downloader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for decryption.
            progress_callback: Optional callback for progress updates.
            max_retries: Maximum retry attempts for chunk downloads.
        """
        self._client = client
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._max_retries = max_retries

    def download_file(
        self,
        server_file: ServerFile,
        local_path: Path,
    ) -> DownloadResult:
        """Download a file from the server with atomic write.

        Uses a temporary file (.tmp) during download, then atomically
        renames to the target path on success. This ensures no partial
        files are left on disk if download is interrupted.

        Args:
            server_file: File metadata from server.
            local_path: Absolute path where to save the file.

        Returns:
            DownloadResult with local metadata.

        Raises:
            DownloadError: If download fails after all retries.
        """
        logger.info(f"Downloading {server_file.path}")

        # Get chunk hashes
        chunk_hashes = self._client.get_file_chunks(server_file.path)

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Use temporary file for atomic write
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")

        try:
            # Download and assemble chunks to temp file
            bytes_transferred = 0
            with open(tmp_path, "wb") as f:
                for i, chunk_hash in enumerate(chunk_hashes):
                    try:
                        # Download chunk with retry
                        encrypted = self._download_chunk_with_retry(chunk_hash)
                        decrypted = decrypt_chunk(encrypted, self._key)
                        f.write(decrypted)
                        bytes_transferred += len(decrypted)
                        logger.debug(
                            f"Downloaded chunk {i + 1}/{len(chunk_hashes)}: "
                            f"{chunk_hash[:8]}..."
                        )

                        # Report progress
                        if self._progress_callback:
                            self._progress_callback(SyncProgress(
                                file_path=server_file.path,
                                file_size=server_file.size,
                                current_chunk=i + 1,
                                total_chunks=len(chunk_hashes),
                                bytes_transferred=bytes_transferred,
                                operation="download",
                            ))
                    except NotFoundError as e:
                        raise DownloadError(
                            f"Chunk {chunk_hash} not found for {server_file.path}"
                        ) from e
                    except Exception as e:
                        raise DownloadError(
                            f"Failed to download chunk {chunk_hash}: {e}"
                        ) from e

            # Atomic rename: tmp -> final path
            # On Windows, need to remove existing file first
            if local_path.exists():
                local_path.unlink()
            tmp_path.rename(local_path)

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

        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            raise

    def _download_chunk_with_retry(self, chunk_hash: str) -> bytes:
        """Download a chunk with exponential backoff retry.

        Args:
            chunk_hash: Hash of the chunk to download.

        Returns:
            Encrypted chunk data.
        """
        result: bytes = retry_with_backoff(
            func=lambda: self._client.download_chunk(chunk_hash),
            max_retries=self._max_retries,
            retryable_exceptions=(OSError, ConnectionError, TimeoutError),
        )
        return result


@dataclass
class ConflictInfo:
    """Information about a detected conflict."""

    original_path: str
    conflict_path: str
    local_hash: str
    server_hash: str
    machine_name: str
    timestamp: str


@dataclass
class SyncResult:
    """Result of a sync operation."""

    uploaded: list[str]
    downloaded: list[str]
    deleted: list[str]
    conflicts: list[str]
    errors: list[str]

    @property
    def has_conflicts(self) -> bool:
        """Check if there are any conflicts."""
        return len(self.conflicts) > 0


# Type alias for conflict notification callback
ConflictCallback = Callable[[ConflictInfo], None]


class SyncEngine:
    """Coordinates file synchronization between local and server."""

    def __init__(
        self,
        client: SyncClient,
        state: SyncState,
        base_path: Path,
        encryption_key: bytes,
        progress_callback: ProgressCallback | None = None,
        conflict_callback: ConflictCallback | None = None,
    ) -> None:
        """Initialize the sync engine.

        Args:
            client: HTTP client for server communication.
            state: Local state database.
            base_path: Base directory for synced files.
            encryption_key: 32-byte AES key for encryption.
            progress_callback: Optional callback for progress updates.
            conflict_callback: Optional callback when conflicts are detected.
        """
        self._client = client
        self._state = state
        self._base_path = Path(base_path).resolve()
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._conflict_callback = conflict_callback
        # Pass state to uploader for resume capability
        self._uploader = FileUploader(
            client, encryption_key, progress_callback, state=state
        )
        self._downloader = FileDownloader(client, encryption_key, progress_callback)
        self._machine_name = get_machine_name()

    def sync(self) -> SyncResult:
        """Perform a full sync operation.

        Returns:
            SyncResult with lists of uploaded, downloaded, deleted, and conflict files.
        """
        uploaded: list[str] = []
        downloaded: list[str] = []
        deleted: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []

        # 0. Scan local folder for new/modified/deleted files
        self._scan_local_changes()

        # 1. Push local changes to server (including deletions)
        push_result = self._push_changes()
        uploaded.extend(push_result["uploaded"])
        deleted.extend(push_result["deleted"])
        conflicts.extend(push_result["conflicts"])
        errors.extend(push_result["errors"])

        # 2. Pull remote changes from server
        pull_result = self._pull_changes()
        downloaded.extend(pull_result["downloaded"])
        errors.extend(pull_result["errors"])

        return SyncResult(
            uploaded=uploaded,
            downloaded=downloaded,
            deleted=deleted,
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
        server_file: ServerFile | None = None

        if local_file and local_file.server_version:
            parent_version = local_file.server_version
            # Also fetch server file for conflict detection
            with contextlib.suppress(NotFoundError):
                server_file = self._client.get_file(relative_path)
        else:
            # Check if file exists on server (handles case where local state is out of sync)
            try:
                server_file = self._client.get_file(relative_path)
                parent_version = server_file.version
                logger.debug(f"File {relative_path} exists on server with version {parent_version}")
            except NotFoundError:
                # File truly doesn't exist on server, will be created
                pass

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
            # Intelligent conflict detection
            return self._handle_conflict(relative_path, local_path, server_file)

    def _handle_conflict(
        self,
        relative_path: str,
        local_path: Path,
        server_file: ServerFile | None,
    ) -> UploadResult | None:
        """Handle a conflict with intelligent detection.

        Checks if it's a real conflict or a false positive:
        - Same hash on both sides → auto-resolve (no real conflict)
        - Different content → create conflict copy

        Args:
            relative_path: Relative path of the file.
            local_path: Absolute path to local file.
            server_file: Server file metadata (may be None).

        Returns:
            UploadResult if auto-resolved, None if real conflict.
        """
        # Calculate local file hash
        local_hash = self._compute_file_hash(local_path)

        # Check if server has the same content (false conflict)
        if server_file and server_file.content_hash == local_hash:
            logger.info(
                f"False conflict for {relative_path}: same content on both sides, auto-resolving"
            )
            # Just update local state to match server
            self._state.mark_synced(
                relative_path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(relative_path),
            )
            self._state.update_file(
                relative_path,
                local_mtime=local_path.stat().st_mtime,
                local_size=local_path.stat().st_size,
                local_hash=local_hash,
            )
            # Return a synthetic result indicating success
            return UploadResult(
                path=relative_path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(relative_path),
                size=server_file.size,
                content_hash=server_file.content_hash,
            )

        # Real conflict - create conflict copy
        logger.warning(f"Real conflict detected for {relative_path}")
        conflict_path = generate_conflict_filename(local_path, self._machine_name)

        # Rename local file to conflict copy
        try:
            local_path.rename(conflict_path)
            logger.info(f"Created conflict copy: {conflict_path.name}")
        except OSError as e:
            logger.error(f"Failed to create conflict copy: {e}")
            self._state.mark_conflict(relative_path)
            return None

        # Download server version to original path
        if server_file:
            try:
                self._downloader.download_file(server_file, local_path)
                # Update state to match server
                self._state.mark_synced(
                    relative_path,
                    server_file_id=server_file.id,
                    server_version=server_file.version,
                    chunk_hashes=self._client.get_file_chunks(relative_path),
                )
            except Exception as e:
                logger.error(f"Failed to download server version: {e}")
                # Restore local file
                conflict_path.rename(local_path)
                self._state.mark_conflict(relative_path)
                return None

        # Notify about conflict
        conflict_info = ConflictInfo(
            original_path=relative_path,
            conflict_path=str(conflict_path.relative_to(self._base_path)),
            local_hash=local_hash,
            server_hash=server_file.content_hash if server_file else "",
            machine_name=self._machine_name,
            timestamp=datetime.now().isoformat(),
        )

        if self._conflict_callback:
            self._conflict_callback(conflict_info)

        self._state.mark_conflict(relative_path)
        return None

    def _compute_file_hash(self, path: Path) -> str:
        """Compute SHA-256 hash of a file."""
        hasher = hashlib.sha256()
        with open(path, "rb") as f:
            for block in iter(lambda: f.read(8192), b""):
                hasher.update(block)
        return hasher.hexdigest()

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

    def _scan_local_changes(self) -> None:
        """Scan local folder for new, modified, or deleted files.

        Walks the sync folder and compares with the state database to find:
        - New files (not in state DB)
        - Modified files (different mtime or size)
        - Deleted files (in state DB but not on disk)
        """
        from syncagent.client.watcher import IgnorePatterns

        # Use the same ignore patterns as the watcher
        ignore = IgnorePatterns()
        syncignore_path = self._base_path / ".syncignore"
        ignore.load_from_file(syncignore_path)

        # Track files found on disk
        found_paths: set[str] = set()

        for root_str, dirs, files in os.walk(self._base_path):
            root = Path(root_str)

            # Filter out ignored directories
            dirs[:] = [
                d for d in dirs
                if not ignore.should_ignore(root / d, self._base_path)
            ]

            for filename in files:
                file_path = root / filename

                if ignore.should_ignore(file_path, self._base_path):
                    continue

                relative_path = str(file_path.relative_to(self._base_path))
                # Normalize path separators
                relative_path = relative_path.replace("\\", "/")
                found_paths.add(relative_path)

                local_file = self._state.get_file(relative_path)
                stat = file_path.stat()

                if local_file is None:
                    # New file - add to state
                    logger.debug(f"Found new local file: {relative_path}")
                    self._state.add_file(
                        relative_path,
                        local_mtime=stat.st_mtime,
                        local_size=stat.st_size,
                        local_hash="",  # Will be computed on upload
                        status=FileStatus.NEW,
                    )
                elif local_file.status == FileStatus.SYNCED:
                    # Check if modified since last sync
                    local_mtime = local_file.local_mtime or 0.0
                    if (
                        stat.st_mtime > local_mtime
                        or stat.st_size != local_file.local_size
                    ):
                        logger.debug(f"Found modified local file: {relative_path}")
                        self._state.mark_modified(relative_path)

        # Check for deleted files (in state DB but not on disk)
        synced_files = self._state.list_files(status=FileStatus.SYNCED)
        for local_file in synced_files:
            if local_file.path not in found_paths:
                # File was deleted locally
                logger.debug(f"Found deleted local file: {local_file.path}")
                self._state.mark_deleted(local_file.path)

    def _push_changes(self) -> dict[str, list[str]]:
        """Push local changes to server.

        Returns:
            Dict with uploaded, deleted, conflicts, and errors lists.
        """
        uploaded: list[str] = []
        deleted: list[str] = []
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

        # Process deletions
        deleted_files = self._state.list_files(status=FileStatus.DELETED)
        for local_file in deleted_files:
            try:
                self._client.delete_file(local_file.path)
                self._state.remove_file(local_file.path)
                deleted.append(local_file.path)
                logger.info(f"Deleted {local_file.path} from server")
            except NotFoundError:
                # File already deleted on server, just clean up local state
                self._state.remove_file(local_file.path)
                deleted.append(local_file.path)
                logger.debug(f"File {local_file.path} already deleted on server")
            except Exception as e:
                logger.error(f"Failed to delete {local_file.path}: {e}")
                errors.append(f"{local_file.path}: {e}")

        return {"uploaded": uploaded, "deleted": deleted, "conflicts": conflicts, "errors": errors}

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
