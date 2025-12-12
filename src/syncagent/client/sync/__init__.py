"""Sync operations for file upload and download.

This package provides:
- FileUploader: Upload files with chunking and encryption
- FileDownloader: Download files with decryption and assembly
- SyncEngine: Coordinate push/pull synchronization
- Conflict detection and resolution utilities
- Retry logic with network awareness

All public symbols are re-exported here for backwards compatibility.
"""

from syncagent.client.sync.conflict import (
    generate_conflict_filename,
    get_machine_name,
)
from syncagent.client.sync.download import FileDownloader
from syncagent.client.sync.engine import SyncEngine
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
    DownloadError,
    DownloadResult,
    ProgressCallback,
    SyncError,
    SyncProgress,
    SyncResult,
    UploadError,
    UploadResult,
)
from syncagent.client.sync.upload import FileUploader

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
    "SyncProgress",
    "SyncResult",
    "UploadError",
    "UploadResult",
    # Classes
    "FileDownloader",
    "FileUploader",
    "SyncEngine",
    # Conflict utilities
    "generate_conflict_filename",
    "get_machine_name",
]
