"""Sync operations for file upload and download.

This package provides:
- FileUploader: Upload files with chunking and encryption
- FileDownloader: Download files with decryption and assembly
- SyncEngine: Coordinate push/pull synchronization
- FileWatcher: Watch directory for changes with debouncing
- EventQueue: Thread-safe priority queue for sync events
- Conflict detection and resolution utilities
- Retry logic with network awareness

All public symbols are re-exported here for backwards compatibility.
"""

from syncagent.client.sync.conflict import (
    generate_conflict_filename,
    get_machine_name,
)
from syncagent.client.sync.coordinator import SyncCoordinator
from syncagent.client.sync.download import FileDownloader
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
from syncagent.client.sync.upload import FileUploader
from syncagent.client.sync.watcher import (
    ChangeType,
    FileChange,
    FileWatcher,
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
    "DownloadResult",
    "ProgressCallback",
    "SyncError",
    "SyncEvent",
    "SyncEventSource",
    "SyncEventType",
    "SyncProgress",
    "SyncResult",
    "UploadError",
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
    # Conflict utilities
    "generate_conflict_filename",
    "get_machine_name",
    # Watcher
    "ChangeType",
    "FileChange",
    "FileWatcher",
    "IgnorePatterns",
]
