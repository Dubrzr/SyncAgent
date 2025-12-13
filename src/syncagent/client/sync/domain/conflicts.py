"""Conflict types and exceptions.

This module provides:
- ConflictOutcome: Result of conflict detection/resolution
- RaceConditionError: Exception for race conditions during resolution

Note: The actual conflict resolution logic (downloading server version,
renaming local files) is in workers/transfers/conflict.py which handles
the full resolution including state updates and notifications.
"""

from __future__ import annotations

from enum import Enum, auto


class ConflictOutcome(Enum):
    """Result of conflict detection/resolution."""

    NO_CONFLICT = auto()  # Safe to proceed
    ALREADY_SYNCED = auto()  # Same content, no real conflict
    RESOLVED = auto()  # Local renamed, proceed with transfer
    RETRY_NEEDED = auto()  # Race condition, need to retry
    ABORT = auto()  # Cannot resolve, abort transfer


class RaceConditionError(Exception):
    """Raised when a file is modified during conflict resolution."""

    pass
