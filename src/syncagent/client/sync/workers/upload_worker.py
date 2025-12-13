"""Upload worker for async file uploads.

This module provides:
- UploadWorker: Worker that wraps FileUploader with cancellation support
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.api import ConflictError
from syncagent.client.sync.types import EarlyConflictError, UploadResult
from syncagent.client.sync.workers.base import (
    BaseWorker,
    CancelledException,
    WorkerContext,
)
from syncagent.client.sync.workers.transfers import FileUploader, UploadCancelledError
from syncagent.client.sync.workers.transfers.conflict import ConflictOutcome, resolve_upload_conflict

if TYPE_CHECKING:
    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState

logger = logging.getLogger(__name__)


class UploadWorker(BaseWorker):
    """Worker for uploading files to the server.

    Wraps FileUploader with cancellation support and progress reporting.

    Usage:
        worker = UploadWorker(client, key, base_path, state)
        success = worker.execute(event, on_progress=callback)
    """

    def __init__(
        self,
        client: HTTPClient,
        encryption_key: bytes,
        base_path: Path,
        sync_state: LocalSyncState | None = None,
    ) -> None:
        """Initialize the upload worker.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for encryption.
            base_path: Base directory for resolving relative paths.
            sync_state: Optional SyncState for tracking upload progress.
        """
        super().__init__()
        self._client = client
        self._key = encryption_key
        self._base_path = base_path
        self._sync_state = sync_state

    @property
    def worker_type(self) -> str:
        """Return worker type name."""
        return "upload"

    def _do_work(self, ctx: WorkerContext) -> UploadResult:
        """Perform the upload.

        Args:
            ctx: Worker context with event and cancellation check.

        Returns:
            UploadResult with server metadata.

        Raises:
            CancelledException: If upload is cancelled.
            UploadError: If upload fails.
        """
        event = ctx.event
        relative_path = event.path
        local_path = self._base_path / relative_path

        # Get parent version from event metadata if updating
        parent_version = event.metadata.get("parent_version")
        if parent_version is not None:
            parent_version = int(parent_version)

        # Create progress adapter
        def progress_adapter(current: int, total: int) -> None:
            if ctx.on_progress:
                ctx.on_progress(current, total)

        # Create uploader with progress callback
        uploader = FileUploader(
            client=self._client,
            encryption_key=self._key,
            progress_callback=lambda p: progress_adapter(p.bytes_transferred, p.file_size),
            state=self._sync_state,
        )

        try:
            result = uploader.upload_file(
                local_path=local_path,
                relative_path=relative_path,
                parent_version=parent_version,
                cancel_check=ctx.cancel_check,
            )
            return result
        except (EarlyConflictError, ConflictError) as e:
            # Conflict detected - resolve using "Server Wins + Local Preserved"
            logger.info(f"Conflict detected for {relative_path}: {e}")
            return self._handle_conflict(relative_path, local_path)
        except UploadCancelledError as e:
            raise CancelledException(str(e)) from e

    def _handle_conflict(self, relative_path: str, local_path: Path) -> UploadResult:
        """Handle a version conflict by resolving with server priority.

        Args:
            relative_path: Relative path of the file.
            local_path: Absolute path to the local file.

        Returns:
            UploadResult indicating the conflict was handled.

        Raises:
            CancelledException: If conflict resolution failed and needs retry.
        """
        if self._sync_state is None:
            raise RuntimeError("Cannot handle conflict without sync state")

        resolution = resolve_upload_conflict(
            client=self._client,
            encryption_key=self._key,
            local_path=local_path,
            relative_path=relative_path,
            state=self._sync_state,
            base_path=self._base_path,
        )

        if resolution.outcome == ConflictOutcome.RETRY_NEEDED:
            # Race condition - let worker pool retry
            raise CancelledException("Conflict resolution failed, retry needed")

        # Both ALREADY_SYNCED and RESOLVED are considered success
        # Get the current server file info to build the result
        server_file = self._client.get_file_metadata(relative_path)

        return UploadResult(
            path=relative_path,
            server_file_id=server_file.id,
            server_version=server_file.version,
            chunk_hashes=[],  # Not relevant for conflict resolution
            size=server_file.size,
            content_hash=server_file.content_hash,
        )
