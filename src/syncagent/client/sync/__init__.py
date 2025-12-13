"""Sync operations for file upload and download.

Architecture:
    ChangeScanner → EventQueue → SyncCoordinator → Workers

Components:
- **ChangeScanner**: Scans local/remote for changes, pushes events to queue
  - Uses /api/changes for incremental remote sync (Phase 14.2)
- **EventQueue**: Thread-safe priority queue for sync events
- **SyncCoordinator**: Processes events, applies decision matrix, dispatches to workers
- **Workers**: Execute transfers (UploadWorker, DownloadWorker, DeleteWorker)
- **WorkerPool**: Concurrent worker management
- **FileWatcher**: Watch directory for real-time changes

Low-level transfer:
- FileUploader / FileDownloader: Chunked transfer with encryption
- Used by workers to perform actual file transfers

All public symbols are re-exported here for backwards compatibility.
"""

from syncagent.client.sync.change_scanner import (
    ChangeScanner,
    LocalChanges,
    RemoteChanges,
    emit_events,
)
from syncagent.client.sync.coordinator import SyncCoordinator
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
from syncagent.client.sync.workers.transfers import (
    DownloadCancelledError,
    FileDownloader,
    FileUploader,
    UploadCancelledError,
)
from syncagent.client.sync.workers.transfers.conflict import (
    ConflictOutcome,
    ConflictResolution,
    RaceConditionError,
    check_download_conflict,
    generate_conflict_filename,
    get_machine_name,
    resolve_upload_conflict,
    safe_rename_for_conflict,
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
    "ChangeScanner",
    "LocalChanges",
    "RemoteChanges",
    # Functions
    "emit_events",
    "FileDownloader",
    "FileUploader",
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
    "ConflictOutcome",
    "ConflictResolution",
    "RaceConditionError",
    "check_download_conflict",
    "generate_conflict_filename",
    "get_machine_name",
    "resolve_upload_conflict",
    "safe_rename_for_conflict",
    # Watcher
    "ChangeType",
    "FileChange",
    "FileWatcher",
    "IgnorePatterns",
]
