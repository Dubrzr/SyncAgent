"""Workers for async transfer operations.

This package provides interruptible workers for file synchronization:
- BaseWorker: Abstract base class with cancellation support
- UploadWorker: Wraps FileUploader for async uploads
- DownloadWorker: Wraps FileDownloader for async downloads
- DeleteWorker: Handles file deletion synchronization
- WorkerPool: Manages concurrent worker threads

Usage:
    from syncagent.client.sync.workers import WorkerPool, TransferType

    pool = WorkerPool(client, key, base_path, max_workers=4)
    pool.start()
    pool.submit(event, TransferType.UPLOAD, on_complete=callback)
    pool.stop()
"""

from syncagent.client.sync.workers.base import (
    BaseWorker,
    CancelledException,
    WorkerContext,
    WorkerResult,
    WorkerState,
)
from syncagent.client.sync.workers.delete_worker import DeleteResult, DeleteWorker
from syncagent.client.sync.workers.download_worker import DownloadWorker
from syncagent.client.sync.workers.pool import PoolState, WorkerPool, WorkerTask
from syncagent.client.sync.workers.upload_worker import UploadWorker

__all__ = [
    # Base
    "BaseWorker",
    "CancelledException",
    "WorkerContext",
    "WorkerResult",
    "WorkerState",
    # Workers
    "DeleteResult",
    "DeleteWorker",
    "DownloadWorker",
    "UploadWorker",
    # Pool
    "PoolState",
    "WorkerPool",
    "WorkerTask",
]
