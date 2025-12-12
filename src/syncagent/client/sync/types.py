"""Shared types and dataclasses for sync operations.

This module provides:
- SyncError, UploadError, DownloadError: Exception classes
- SyncProgress: Progress tracking dataclass
- UploadResult, DownloadResult: Operation result dataclasses
- SyncResult: Overall sync operation result
- ConflictInfo: Conflict detection information
- SyncEventType, SyncEventSource, SyncEvent: Event queue types
- Type aliases for callbacks
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, auto
from pathlib import Path


class SyncError(Exception):
    """Base exception for sync errors."""


class UploadError(SyncError):
    """Failed to upload a file."""


class DownloadError(SyncError):
    """Failed to download a file."""


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
    """Information about a detected conflict."""

    original_path: str
    conflict_path: str
    local_hash: str
    server_hash: str
    machine_name: str
    timestamp: str


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
