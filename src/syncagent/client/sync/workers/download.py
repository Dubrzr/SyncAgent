"""Download worker for async file downloads.

This module provides:
- DownloadWorker: Worker that wraps FileDownloader with cancellation support
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.download import DownloadCancelledError, FileDownloader
from syncagent.client.sync.types import DownloadResult
from syncagent.client.sync.workers.base import (
    BaseWorker,
    CancelledException,
    WorkerContext,
)

if TYPE_CHECKING:
    from syncagent.client.api import SyncClient

logger = logging.getLogger(__name__)


class DownloadWorker(BaseWorker):
    """Worker for downloading files from the server.

    Wraps FileDownloader with cancellation support and progress reporting.

    Usage:
        worker = DownloadWorker(client, key, base_path)
        success = worker.execute(event, on_progress=callback)
    """

    def __init__(
        self,
        client: SyncClient,
        encryption_key: bytes,
        base_path: Path,
    ) -> None:
        """Initialize the download worker.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for decryption.
            base_path: Base directory for resolving relative paths.
        """
        super().__init__()
        self._client = client
        self._key = encryption_key
        self._base_path = base_path

    @property
    def worker_type(self) -> str:
        """Return worker type name."""
        return "download"

    def _do_work(self, ctx: WorkerContext) -> DownloadResult:
        """Perform the download.

        Args:
            ctx: Worker context with event and cancellation check.

        Returns:
            DownloadResult with local metadata.

        Raises:
            CancelledException: If download is cancelled.
            DownloadError: If download fails.
        """
        event = ctx.event
        relative_path = event.path
        local_path = self._base_path / relative_path

        # Get server file metadata
        server_file = self._client.get_file(relative_path)

        # Create progress adapter
        def progress_adapter(current: int, total: int) -> None:
            if ctx.on_progress:
                ctx.on_progress(current, total)

        # Create downloader with progress callback
        downloader = FileDownloader(
            client=self._client,
            encryption_key=self._key,
            progress_callback=lambda p: progress_adapter(p.bytes_transferred, p.file_size),
        )

        try:
            result = downloader.download_file(
                server_file=server_file,
                local_path=local_path,
                cancel_check=ctx.cancel_check,
            )
            return result
        except DownloadCancelledError as e:
            raise CancelledException(str(e)) from e
