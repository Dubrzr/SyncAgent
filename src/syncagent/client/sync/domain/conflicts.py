"""Conflict detection and resolution.

Implements "Server Wins + Local Preserved" strategy:
1. Server version is always downloaded
2. Local changes are preserved as .conflict-* files
3. User decides manually which version to keep

Conflict scenarios:
- Upload conflict: Server changed while uploading
- Download conflict: Local changed after scan, before download
- Concurrent conflict: Remote event while transfer in progress
"""

from __future__ import annotations

import platform
import socket
from dataclasses import dataclass
from datetime import datetime
from enum import Enum, auto
from pathlib import Path
from typing import Protocol


class ConflictType(Enum):
    """When the conflict was detected."""

    PRE_TRANSFER = auto()  # Before transfer started (version check)
    MID_TRANSFER = auto()  # During transfer (periodic check)
    POST_TRANSFER = auto()  # At commit time (VERSION_CONFLICT)
    CONCURRENT_EVENT = auto()  # New event while transfer in progress


class ConflictOutcome(Enum):
    """Result of conflict detection/resolution."""

    NO_CONFLICT = auto()  # Safe to proceed
    ALREADY_SYNCED = auto()  # Same content, no real conflict
    RESOLVED = auto()  # Local renamed, proceed with transfer
    RETRY_NEEDED = auto()  # Race condition, need to retry
    ABORT = auto()  # Cannot resolve, abort transfer


@dataclass
class ConflictContext:
    """All information needed to detect/resolve a conflict."""

    local_path: Path
    relative_path: str
    local_mtime: float | None
    local_size: int | None
    local_hash: str | None
    server_version: int | None
    server_hash: str | None
    expected_version: int | None  # Version we're working against


@dataclass
class ConflictResolution:
    """Result of conflict resolution."""

    outcome: ConflictOutcome
    conflict_path: Path | None = None  # Path to .conflict-* file
    server_version: int | None = None  # New server version after resolution
    message: str = ""  # Human-readable explanation


class ConflictDetector(Protocol):
    """Protocol for detecting conflicts."""

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        """Check if there's a conflict. Does not modify anything."""
        ...


class ConflictResolver(Protocol):
    """Protocol for resolving conflicts."""

    def resolve(self, ctx: ConflictContext) -> ConflictResolution:
        """Resolve a conflict. May rename files, download server version."""
        ...


class PreDownloadConflictDetector:
    """Detects conflicts before a download overwrites local file.

    Scenarios:
    1. Local file exists but untracked -> conflict (appeared after scan)
    2. Local file modified since last sync -> conflict
    3. Local matches tracked state -> no conflict
    """

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        """Check if downloading would overwrite local changes."""
        if not ctx.local_path.exists():
            return ConflictOutcome.NO_CONFLICT

        if ctx.local_mtime is None:
            # Untracked file appeared
            return ConflictOutcome.RESOLVED  # Will need resolution

        try:
            current = ctx.local_path.stat()
        except OSError:
            # File disappeared
            return ConflictOutcome.NO_CONFLICT

        if current.st_mtime > ctx.local_mtime or current.st_size != ctx.local_size:
            return ConflictOutcome.RESOLVED  # Modified, needs resolution

        return ConflictOutcome.NO_CONFLICT


class PreUploadConflictDetector:
    """Detects conflicts before upload by checking server version.

    If server version != expected version, someone else modified the file.
    """

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        """Check if server has newer version than expected."""
        if ctx.expected_version is None:
            return ConflictOutcome.NO_CONFLICT  # New file

        if ctx.server_version is None:
            return ConflictOutcome.RESOLVED  # File deleted on server

        if ctx.server_version != ctx.expected_version:
            return ConflictOutcome.RESOLVED  # Version mismatch

        return ConflictOutcome.NO_CONFLICT


class RaceConditionError(Exception):
    """Raised when a file is modified during conflict resolution."""

    pass


def get_machine_name() -> str:
    """Get a short machine identifier for conflict filenames."""
    try:
        hostname = socket.gethostname()
        # Truncate to reasonable length
        return hostname[:15] if len(hostname) > 15 else hostname
    except OSError:
        return platform.node()[:15] or "unknown"


def generate_conflict_filename(path: Path, machine_name: str | None = None) -> Path:
    """Generate a conflict filename: name.conflict-YYYYMMDD-HHMMSS-machine.ext

    Args:
        path: Original file path
        machine_name: Optional machine identifier (auto-detected if None)

    Returns:
        Path with conflict suffix inserted before extension
    """
    machine = machine_name or get_machine_name()
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S") + f"-{now.microsecond // 1000:03d}"

    return path.parent / f"{path.stem}.conflict-{timestamp}-{machine}{path.suffix}"


def safe_rename(src: Path, dst: Path) -> None:
    """Rename with race condition detection.

    Args:
        src: Source path
        dst: Destination path

    Raises:
        RaceConditionError: If file was modified during rename
        OSError: If rename fails
    """
    mtime_before = src.stat().st_mtime
    src.rename(dst)
    mtime_after = dst.stat().st_mtime

    if mtime_after != mtime_before:
        # Rollback and raise
        dst.rename(src)
        raise RaceConditionError(f"File {src} modified during rename")
