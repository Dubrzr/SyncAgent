"""Sync operations for file upload and download.

This package provides two sync architectures:

1. **Batch sync** (SyncEngine):
   - Scans for changes and syncs them all at once
   - Good for: initial sync, manual "sync now", batch operations

2. **Event-driven sync** (Phase 15):
   - Real-time sync with file watching
   - Components: FileWatcher → EventQueue → SyncCoordinator → Workers
   - Good for: continuous background sync

Components:
- FileUploader / FileDownloader: Chunked transfer with encryption
- SyncEngine: Batch push/pull synchronization
- FileWatcher: Watch directory for changes with debouncing
- EventQueue: Thread-safe priority queue for sync events
- SyncCoordinator: Event-driven orchestrator with decision matrix
- Workers (UploadWorker, DownloadWorker, DeleteWorker): Interruptible workers
- WorkerPool: Concurrent worker management

All public symbols are re-exported here for backwards compatibility.
"""

from syncagent.client.sync.conflict import (
    generate_conflict_filename,
    get_machine_name,
)
from syncagent.client.sync.coordinator import SyncCoordinator
from syncagent.client.sync.download import (
    DownloadCancelledError,
    FileDownloader,
)
from syncagent.client.sync.engine import SyncEngine
from syncagent.client.sync.ignore import IgnorePatterns
from syncagent.client.sync.queue import EventQueue
from syncagent.client.sync.retry import (
    DEFAULT_BACKOFF_MULTIPLIER,
    DEFAULT_INITIAL_BACKOFF,
    DEFAULT_MAX_BACKOFF,
    DEFAULT_MAX_RETRIES,
    NETWORK_CHECK_INTERVAL,
    NETWORK_EXCEPTIONS,
    retry_with_backoff,
    retry_with_network_wait,
    wait_for_network,
)
from syncagent.client.sync.types import (
    ConflictCallback,
    ConflictInfo,
    CoordinatorState,
    CoordinatorStats,
    DownloadError,
    DownloadResult,
    ProgressCallback,
    SyncError,
    SyncEvent,
    SyncEventSource,
    SyncEventType,
    SyncProgress,
    SyncResult,
    TransferState,
    TransferStatus,
    TransferType,
    UploadError,
    UploadResult,
)
from syncagent.client.sync.upload import FileUploader, UploadCancelledError
from syncagent.client.sync.watcher import (
    ChangeType,
    FileChange,
    FileWatcher,
)
from syncagent.client.sync.workers import (
    BaseWorker,
    CancelledException,
    DeleteResult,
    DeleteWorker,
    DownloadWorker,
    PoolState,
    UploadWorker,
    WorkerContext,
    WorkerPool,
    WorkerResult,
    WorkerState,
    WorkerTask,
)

__all__ = [
    # Retry functions and constants
    "DEFAULT_BACKOFF_MULTIPLIER",
    "DEFAULT_INITIAL_BACKOFF",
    "DEFAULT_MAX_BACKOFF",
    "DEFAULT_MAX_RETRIES",
    "NETWORK_CHECK_INTERVAL",
    "NETWORK_EXCEPTIONS",
    "retry_with_backoff",
    "retry_with_network_wait",
    "wait_for_network",
    # Types and dataclasses
    "ConflictCallback",
    "ConflictInfo",
    "DownloadError",
    "DownloadCancelledError",
    "DownloadResult",
    "ProgressCallback",
    "SyncError",
    "SyncEvent",
    "SyncEventSource",
    "SyncEventType",
    "SyncProgress",
    "SyncResult",
    "UploadError",
    "UploadCancelledError",
    "UploadResult",
    # Classes
    "FileDownloader",
    "FileUploader",
    "SyncEngine",
    # Event Queue & Coordinator
    "EventQueue",
    "SyncCoordinator",
    "CoordinatorState",
    "CoordinatorStats",
    "TransferState",
    "TransferStatus",
    "TransferType",
    # Workers
    "BaseWorker",
    "CancelledException",
    "DeleteResult",
    "DeleteWorker",
    "DownloadWorker",
    "PoolState",
    "UploadWorker",
    "WorkerContext",
    "WorkerPool",
    "WorkerResult",
    "WorkerState",
    "WorkerTask",
    # Conflict utilities
    "generate_conflict_filename",
    "get_machine_name",
    # Watcher
    "ChangeType",
    "FileChange",
    "FileWatcher",
    "IgnorePatterns",
]
