"""Shared types and dataclasses for sync operations.

This module provides:
- SyncError, UploadError, DownloadError: Exception classes
- SyncProgress: Progress tracking dataclass
- UploadResult, DownloadResult: Operation result dataclasses
- SyncResult: Overall sync operation result
- ConflictInfo: Conflict detection information
- Type aliases for callbacks
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
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
