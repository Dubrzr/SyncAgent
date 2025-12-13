"""Shared types and dataclasses for sync operations.

This module provides:
- SyncError, UploadError, DownloadError: Exception classes
- SyncProgress: Progress tracking dataclass
- UploadResult, DownloadResult: Operation result dataclasses
- SyncResult: Overall sync operation result
- ConflictInfo: Conflict detection information
- SyncEventType, SyncEventSource, SyncEvent: Event queue types
- TransferType, TransferStatus, TransferState: Coordinator types
- ConflictType: Types of conflicts (pre/mid/post transfer)
- CoordinatorState, CoordinatorStats: Coordinator state
- Type aliases for callbacks
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, auto
from pathlib import Path


@dataclass
class LocalFileInfo:
    """Metadata about a local file for sync events.

    Used to pass mtime/size information from scanner to queue,
    enabling mtime-aware deduplication.
    """

    path: str
    mtime: float
    size: int


class SyncError(Exception):
    """Base exception for sync errors."""


class UploadError(SyncError):
    """Failed to upload a file."""


class DownloadError(SyncError):
    """Failed to download a file."""


class EarlyConflictError(SyncError):
    """Conflict detected before or during transfer (Phase 15.7).

    This allows early cancellation to avoid wasting bandwidth.

    Attributes:
        path: File path with conflict
        expected_version: Version we were uploading against
        actual_version: Current server version
        conflict_type: When the conflict was detected
    """

    def __init__(
        self,
        path: str,
        expected_version: int | None,
        actual_version: int,
        conflict_type: ConflictType,
    ) -> None:
        self.path = path
        self.expected_version = expected_version
        self.actual_version = actual_version
        self.conflict_type = conflict_type
        super().__init__(
            f"Conflict on {path}: expected version {expected_version}, "
            f"server has {actual_version} ({conflict_type.name})"
        )


@dataclass
class SyncProgress:
    """Progress information for sync operations."""

    file_path: str
    file_size: int
    current_chunk: int
    total_chunks: int
    bytes_transferred: int
    operation: str  # "upload" or "download"

    @property
    def percent(self) -> float:
        """Get progress percentage."""
        if self.total_chunks == 0:
            return 100.0
        return (self.current_chunk / self.total_chunks) * 100


# Type alias for progress callback
ProgressCallback = Callable[[SyncProgress], None]


@dataclass
class UploadResult:
    """Result of a file upload operation."""

    path: str
    server_file_id: int
    server_version: int
    chunk_hashes: list[str]
    size: int
    content_hash: str


@dataclass
class DownloadResult:
    """Result of a file download operation."""

    path: str
    local_path: Path
    size: int
    version: int


@dataclass
class ConflictInfo:
    """Information about a detected conflict.

    Attributes:
        original_path: Path of the conflicting file
        conflict_path: Path where conflict copy was saved (if any)
        local_hash: Hash of the local file version
        server_hash: Hash of the server file version
        machine_name: Name of the machine where conflict was detected
        timestamp: When the conflict was detected
        conflict_type: When the conflict was detected (pre/mid/post transfer)
        local_version: Local version being uploaded
        server_version: Server version that caused the conflict
    """

    original_path: str
    conflict_path: str
    local_hash: str
    server_hash: str
    machine_name: str
    timestamp: str
    # Enhanced conflict info (Phase 15.7)
    conflict_type: ConflictType | None = None
    local_version: int | None = None  # Version we were uploading against
    server_version: int | None = None  # Actual server version


@dataclass
class SyncResult:
    """Result of a sync operation."""

    uploaded: list[str]
    downloaded: list[str]
    deleted: list[str]
    conflicts: list[str]
    errors: list[str]

    @property
    def has_conflicts(self) -> bool:
        """Check if there are any conflicts."""
        return len(self.conflicts) > 0


# Type alias for conflict notification callback
ConflictCallback = Callable[[ConflictInfo], None]


# =============================================================================
# Event Queue Types
# =============================================================================


class SyncEventType(IntEnum):
    """Types of sync events.

    Values are ordered by priority (lower = higher priority).
    """

    # High priority - avoid useless transfers
    LOCAL_DELETED = 10
    REMOTE_DELETED = 11

    # Medium priority - local changes
    LOCAL_CREATED = 20
    LOCAL_MODIFIED = 21

    # Lower priority - remote changes
    REMOTE_CREATED = 30
    REMOTE_MODIFIED = 31

    # Internal events (lowest priority)
    TRANSFER_COMPLETE = 90
    TRANSFER_FAILED = 91


class SyncEventSource(IntEnum):
    """Source of sync events."""

    LOCAL = auto()  # From file watcher
    REMOTE = auto()  # From server WebSocket
    INTERNAL = auto()  # From coordinator (transfer results)


@dataclass(order=True)
class SyncEvent:
    """A sync event to be processed by the coordinator.

    Events are ordered by (priority, timestamp) for queue processing.
    The priority field is computed from event_type for proper ordering.

    Attributes:
        event_type: The type of sync event
        path: Relative path of the file (from sync root)
        source: Where the event originated
        timestamp: Unix timestamp when event was created
        event_id: Unique identifier for this event
        priority: Computed priority for queue ordering (lower = higher priority)
        metadata: Optional additional data (e.g., server version, file hash)
    """

    # Fields used for ordering (in order)
    priority: int = field(compare=True)
    timestamp: float = field(compare=True)

    # Main fields (not used for ordering)
    event_type: SyncEventType = field(compare=False)
    path: str = field(compare=False)
    source: SyncEventSource = field(compare=False)
    event_id: str = field(compare=False)
    metadata: dict[str, str | int | float] = field(
        default_factory=dict, compare=False
    )

    @classmethod
    def create(
        cls,
        event_type: SyncEventType,
        path: str,
        source: SyncEventSource,
        metadata: dict[str, str | int | float] | None = None,
    ) -> SyncEvent:
        """Create a new SyncEvent with auto-generated id and timestamp.

        Args:
            event_type: The type of event
            path: Relative file path
            source: Event origin
            metadata: Optional additional data

        Returns:
            A new SyncEvent instance
        """
        timestamp = time.time()
        # Event ID format: timestamp_type_path_hash
        event_id = f"{timestamp:.6f}_{event_type.name}_{hash(path) & 0xFFFFFFFF:08x}"
        return cls(
            priority=int(event_type),
            timestamp=timestamp,
            event_type=event_type,
            path=path,
            source=source,
            event_id=event_id,
            metadata=metadata or {},
        )

    def __repr__(self) -> str:
        """Human-readable representation."""
        return (
            f"SyncEvent({self.event_type.name}, "
            f"path={self.path!r}, "
            f"source={self.source.name})"
        )


# =============================================================================
# Coordinator Types
# =============================================================================


class TransferType(IntEnum):
    """Type of transfer operation."""

    UPLOAD = auto()
    DOWNLOAD = auto()
    DELETE = auto()


class ConflictType(IntEnum):
    """Type of conflict detected.

    Distinguishes when the conflict was detected for better handling:
    - PRE_TRANSFER: Detected before transfer started (cheapest to handle)
    - MID_TRANSFER: Detected during transfer (some wasted bandwidth)
    - POST_TRANSFER: Detected at commit time (all bandwidth wasted)
    - CONCURRENT_EVENT: Detected from concurrent remote event
    """

    PRE_TRANSFER = auto()  # Version mismatch before starting upload
    MID_TRANSFER = auto()  # Version changed during upload (periodic check)
    POST_TRANSFER = auto()  # Version mismatch at update_file() call
    CONCURRENT_EVENT = auto()  # Remote event arrived during upload


class TransferStatus(IntEnum):
    """Status of a transfer operation."""

    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


class CoordinatorState(IntEnum):
    """State of the coordinator."""

    STOPPED = auto()
    RUNNING = auto()
    STOPPING = auto()


@dataclass
class TransferState:
    """Tracks the state of an in-progress transfer.

    Attributes:
        path: Relative file path
        transfer_type: Type of operation (upload/download/delete)
        status: Current status
        event: The event that triggered this transfer
        started_at: When the transfer started
        cancel_requested: Flag to request cancellation
        error: Error message if failed
        base_version: Server version this transfer is based on (for uploads)
        detected_server_version: Latest server version detected during transfer
        conflict_type: Type of conflict if one was detected
    """

    path: str
    transfer_type: TransferType
    status: TransferStatus
    event: SyncEvent
    started_at: float = field(default_factory=time.time)
    cancel_requested: bool = False
    error: str | None = None
    # In-flight version tracking (Phase 15.7)
    base_version: int | None = None  # Version we're uploading against
    detected_server_version: int | None = None  # Latest server version we detected
    conflict_type: ConflictType | None = None  # Type of conflict if detected

    def request_cancel(self) -> None:
        """Request cancellation of this transfer."""
        self.cancel_requested = True

    def set_conflict(
        self,
        conflict_type: ConflictType,
        detected_version: int | None = None,
    ) -> None:
        """Mark this transfer as having a conflict.

        Args:
            conflict_type: When/how the conflict was detected
            detected_version: The server version that caused the conflict
        """
        self.conflict_type = conflict_type
        if detected_version is not None:
            self.detected_server_version = detected_version
        self.request_cancel()  # Auto-cancel on conflict


@dataclass
class CoordinatorStats:
    """Statistics for the coordinator."""

    events_processed: int = 0
    uploads_completed: int = 0
    downloads_completed: int = 0
    deletes_completed: int = 0
    transfers_cancelled: int = 0
    conflicts_detected: int = 0
    errors: int = 0
