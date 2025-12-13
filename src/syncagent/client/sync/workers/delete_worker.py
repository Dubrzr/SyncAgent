"""Delete worker for file deletion synchronization.

This module provides:
- DeleteWorker: Worker that handles file deletion (local and remote)
- DeleteResult: Result of a delete operation
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.types import SyncEventSource
from syncagent.client.sync.workers.base import (
    BaseWorker,
    WorkerContext,
)

if TYPE_CHECKING:
    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState

logger = logging.getLogger(__name__)


@dataclass
class DeleteResult:
    """Result of a delete operation.

    Attributes:
        path: The deleted file path.
        deleted_local: Whether the local file was deleted.
        deleted_remote: Whether the remote file was deleted.
    """

    path: str
    deleted_local: bool = False
    deleted_remote: bool = False


class DeleteWorker(BaseWorker):
    """Worker for deleting files locally or on the server.

    Handles both directions:
    - LOCAL_DELETED events: Propagate deletion to server
    - REMOTE_DELETED events: Delete local file

    Usage:
        worker = DeleteWorker(client, base_path)
        success = worker.execute(event)
    """

    def __init__(
        self,
        client: HTTPClient,
        base_path: Path,
        sync_state: LocalSyncState | None = None,
    ) -> None:
        """Initialize the delete worker.

        Args:
            client: HTTP client for server communication.
            base_path: Base directory for resolving relative paths.
            sync_state: Local sync state for tracking (optional).
        """
        super().__init__()
        self._client = client
        self._base_path = base_path
        self._state = sync_state

    @property
    def worker_type(self) -> str:
        """Return worker type name."""
        return "delete"

    def _do_work(self, ctx: WorkerContext) -> DeleteResult:
        """Perform the deletion.

        Args:
            ctx: Worker context with event and cancellation check.

        Returns:
            DeleteResult indicating what was deleted.

        Raises:
            Exception: If deletion fails.
        """
        event = ctx.event
        relative_path = event.path
        local_path = self._base_path / relative_path

        result = DeleteResult(path=relative_path)

        if event.source == SyncEventSource.LOCAL:
            # Local file was deleted, propagate to server
            logger.info(f"Propagating local deletion to server: {relative_path}")
            try:
                self._client.delete_file(relative_path)
                result.deleted_remote = True
                logger.info(f"Deleted on server: {relative_path}")
                # Remove from local state so it's no longer tracked
                if self._state:
                    self._state.mark_deleted(relative_path)
            except Exception as e:
                logger.error(f"Failed to delete on server: {relative_path}: {e}")
                raise

        elif event.source == SyncEventSource.REMOTE:
            # Remote file was deleted, delete local
            logger.info(f"Deleting local file due to remote deletion: {relative_path}")
            if local_path.exists():
                try:
                    if local_path.is_dir():
                        # For directories, use rmdir (must be empty)
                        local_path.rmdir()
                    else:
                        local_path.unlink()
                    result.deleted_local = True
                    logger.info(f"Deleted locally: {relative_path}")
                except Exception as e:
                    logger.error(f"Failed to delete locally: {relative_path}: {e}")
                    raise
            else:
                # File already doesn't exist locally
                logger.debug(f"Local file already deleted: {relative_path}")
                result.deleted_local = True

            # Remove from local state so it's no longer tracked
            if self._state:
                self._state.mark_deleted(relative_path)

        return result
