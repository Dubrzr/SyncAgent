"""Upload worker for async file uploads.

This module provides:
- UploadWorker: Worker that wraps FileUploader with cancellation support
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.types import EarlyConflictError, UploadResult
from syncagent.client.sync.upload import FileUploader, UploadCancelledError
from syncagent.client.sync.workers.base import (
    BaseWorker,
    CancelledException,
    WorkerContext,
)


class EarlyConflictException(CancelledException):
    """Raised when an early conflict is detected (Phase 15.7).

    Contains the original EarlyConflictError with conflict details.
    """

    def __init__(self, error: EarlyConflictError) -> None:
        super().__init__(str(error))
        self.conflict_error = error

if TYPE_CHECKING:
    from syncagent.client.api import SyncClient
    from syncagent.client.state import SyncState

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
        client: SyncClient,
        encryption_key: bytes,
        base_path: Path,
        sync_state: SyncState | None = None,
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
        except EarlyConflictError as e:
            # Phase 15.7: Early conflict detection
            raise EarlyConflictException(e) from e
        except UploadCancelledError as e:
            raise CancelledException(str(e)) from e
