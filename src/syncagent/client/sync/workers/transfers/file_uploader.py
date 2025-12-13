"""File upload with chunking and encryption.

This module provides:
- FileUploader: Handles file upload with resumable chunk support
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.retry import DEFAULT_MAX_RETRIES, retry_with_network_wait
from syncagent.client.sync.types import (
    ConflictType,
    EarlyConflictError,
    ProgressCallback,
    SyncProgress,
    UploadError,
    UploadResult,
)
from syncagent.core.chunking import Chunk, chunk_file
from syncagent.core.crypto import compute_file_hash, encrypt_chunk

if TYPE_CHECKING:
    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState

from syncagent.client.api import ConflictError

logger = logging.getLogger(__name__)

# Number of chunks between mid-transfer version checks (Phase 15.7)
VERSION_CHECK_INTERVAL = 10


class UploadCancelledError(UploadError):
    """Raised when an upload is cancelled."""

    pass


class FileUploader:
    """Handles file upload with chunking and encryption.

    Supports resumable uploads at chunk level for robustness against
    network interruptions.
    """

    def __init__(
        self,
        client: HTTPClient,
        encryption_key: bytes,
        progress_callback: ProgressCallback | None = None,
        state: LocalSyncState | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
        enable_early_conflict_check: bool = True,
        version_check_interval: int = VERSION_CHECK_INTERVAL,
    ) -> None:
        """Initialize the uploader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for encryption.
            progress_callback: Optional callback for progress updates.
            state: Optional SyncState for tracking upload progress (enables resume).
            max_retries: Maximum retry attempts for chunk uploads.
            enable_early_conflict_check: Check version before/during upload (Phase 15.7).
            version_check_interval: Chunks between mid-transfer version checks.
        """
        self._client = client
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._state = state
        self._max_retries = max_retries
        self._enable_early_conflict_check = enable_early_conflict_check
        self._version_check_interval = version_check_interval

    def upload_file(
        self,
        local_path: Path,
        relative_path: str,
        parent_version: int | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> UploadResult:
        """Upload a file to the server with resumable chunk uploads.

        If state tracking is enabled, upload progress is saved after each
        chunk, allowing interrupted uploads to resume from where they left off.

        Phase 15.7 enhancements:
        - Pre-upload version check to detect conflicts early
        - Periodic mid-transfer version checks for long uploads

        Args:
            local_path: Absolute path to the local file.
            relative_path: Relative path for storage on server.
            parent_version: Expected current version for updates (None for new files).
            cancel_check: Optional function that returns True if upload should be cancelled.

        Returns:
            UploadResult with server metadata.

        Raises:
            UploadError: If upload fails after all retries.
            UploadCancelledError: If upload is cancelled.
            EarlyConflictError: If version conflict detected early (Phase 15.7).
            ConflictError: If version conflict detected at commit.
        """
        if not local_path.exists():
            raise UploadError(f"File not found: {local_path}")

        logger.info(f"Uploading {relative_path}")

        # Phase 15.7: Pre-upload version check
        if self._enable_early_conflict_check and parent_version is not None:
            self._check_server_version(relative_path, parent_version, ConflictType.PRE_TRANSFER)

        # Chunk the file
        chunks = list(chunk_file(local_path))
        chunk_hashes = [c.hash for c in chunks]

        # Calculate file hash
        content_hash = compute_file_hash(local_path)
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
        chunks_since_version_check = 0
        for i, chunk in enumerate(chunks):
            # Check for cancellation before each chunk
            if cancel_check and cancel_check():
                logger.info(f"Upload cancelled at chunk {i + 1}/{len(chunks)}")
                raise UploadCancelledError(
                    f"Upload of {relative_path} cancelled at chunk {i + 1}/{len(chunks)}"
                )

            # Phase 15.7: Mid-transfer version check (periodic)
            if (
                self._enable_early_conflict_check
                and parent_version is not None
                and chunks_since_version_check >= self._version_check_interval
            ):
                self._check_server_version(
                    relative_path, parent_version, ConflictType.MID_TRANSFER
                )
                chunks_since_version_check = 0

            # Skip already uploaded chunks
            if chunk.hash in already_uploaded:
                bytes_transferred += len(chunk.data)
                logger.debug(f"Skipping already uploaded chunk {chunk.hash[:8]}...")
            else:
                self._upload_chunk_with_retry(chunk, relative_path)
                bytes_transferred += len(chunk.data)
                chunks_since_version_check += 1

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
            # New file - try create, fall back to update if already exists
            try:
                server_file = self._client.create_file(
                    path=relative_path,
                    size=size,
                    content_hash=content_hash,
                    chunks=chunk_hashes,
                )
            except ConflictError:
                # File already exists on server - fetch current version and update
                logger.info(
                    f"File {relative_path} already exists on server, "
                    "falling back to update"
                )
                existing = self._client.get_file_metadata(relative_path)
                server_file = self._client.update_file(
                    path=relative_path,
                    size=size,
                    content_hash=content_hash,
                    parent_version=existing.version,
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

        # Clear upload progress and mark as synced with current file stats
        if self._state:
            self._state.clear_upload_progress(relative_path)
            stat = local_path.stat()
            self._state.mark_synced(
                relative_path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=chunk_hashes,
                local_mtime=stat.st_mtime,
                local_size=stat.st_size,
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

    def _upload_chunk_with_retry(self, chunk: Chunk, relative_path: str) -> None:
        """Upload a chunk with network-aware retry and progress tracking.

        Uses retry_with_network_wait which waits indefinitely for network
        to be restored on connectivity errors, rather than failing.

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

        # Upload with network-aware retry
        encrypted = encrypt_chunk(chunk.data, self._key)

        def do_upload() -> None:
            self._client.upload_chunk(chunk.hash, encrypted)

        retry_with_network_wait(
            func=do_upload,
            client=self._client,
            max_retries=self._max_retries,
            retryable_exceptions=(Exception,),  # Retry all, network handled separately
        )

        # Track progress
        if self._state:
            self._state.mark_chunk_uploaded(relative_path, chunk.hash)

        logger.debug(f"Uploaded chunk {chunk.hash[:8]}...")

    def _check_server_version(
        self,
        relative_path: str,
        expected_version: int,
        conflict_type: ConflictType,
    ) -> None:
        """Check if server version matches expected (Phase 15.7).

        This allows early conflict detection to avoid wasting bandwidth
        uploading chunks that will be rejected anyway.

        Args:
            relative_path: File path to check.
            expected_version: Version we're uploading against.
            conflict_type: When this check is happening (pre/mid transfer).

        Raises:
            EarlyConflictError: If server version doesn't match expected.
        """
        from syncagent.client.api import NotFoundError

        try:
            server_file = self._client.get_file_metadata(relative_path)
            actual_version = server_file.version

            if actual_version != expected_version:
                logger.warning(
                    f"Early conflict detected on {relative_path}: "
                    f"expected v{expected_version}, server has v{actual_version} "
                    f"({conflict_type.name})"
                )
                raise EarlyConflictError(
                    path=relative_path,
                    expected_version=expected_version,
                    actual_version=actual_version,
                    conflict_type=conflict_type,
                )

            logger.debug(
                f"Version check passed for {relative_path}: v{actual_version} "
                f"({conflict_type.name})"
            )

        except NotFoundError:
            # File was deleted on server - also a conflict for updates
            logger.warning(
                f"Conflict: {relative_path} was deleted on server "
                f"(expected v{expected_version})"
            )
            raise EarlyConflictError(
                path=relative_path,
                expected_version=expected_version,
                actual_version=-1,  # Deleted
                conflict_type=conflict_type,
            ) from None
