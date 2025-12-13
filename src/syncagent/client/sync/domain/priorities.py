"""Event priority and ordering logic.

This module defines:
- Priority levels for sync events
- Ordering rules for queue processing
- Deduplication strategy (mtime-aware)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncagent.client.sync.types import SyncEvent


class Priority(IntEnum):
    """Event priority levels (lower = higher priority)."""

    CRITICAL = 10  # Deletions - avoid useless transfers
    HIGH = 20  # Local changes - user's work
    NORMAL = 30  # Remote changes - other machines
    LOW = 90  # Internal events - transfer results


@dataclass(frozen=True)
class PriorityRule:
    """Maps event type to priority level."""

    event_type: str
    priority: Priority
    reason: str


# Declarative priority rules
PRIORITY_RULES: list[PriorityRule] = [
    PriorityRule("LOCAL_DELETED", Priority.CRITICAL, "Avoid uploading then deleting"),
    PriorityRule("REMOTE_DELETED", Priority.CRITICAL, "Clean up local quickly"),
    PriorityRule("LOCAL_CREATED", Priority.HIGH, "User created file"),
    PriorityRule("LOCAL_MODIFIED", Priority.HIGH, "User modified file"),
    PriorityRule("REMOTE_CREATED", Priority.NORMAL, "Download new remote file"),
    PriorityRule("REMOTE_MODIFIED", Priority.NORMAL, "Download remote changes"),
    PriorityRule("TRANSFER_COMPLETE", Priority.LOW, "Internal bookkeeping"),
    PriorityRule("TRANSFER_FAILED", Priority.LOW, "Internal bookkeeping"),
]


class EventComparator(Protocol):
    """Protocol for comparing events for deduplication."""

    def should_replace(self, old_event: SyncEvent, new_event: SyncEvent) -> bool:
        """Return True if new_event should replace old_event."""
        ...


class MtimeAwareComparator:
    """Compares events by file mtime, falls back to event timestamp.

    This ensures that if a file is modified during a scan:
    - The watcher's event (with current mtime) wins
    - The scanner's event (with stale mtime) is ignored
    """

    def should_replace(self, old_event: SyncEvent, new_event: SyncEvent) -> bool:
        """Return True if new_event should replace old_event.

        Comparison logic:
        1. If both have mtime, compare mtime (newer wins)
        2. If same mtime, compare event timestamp (newer wins)
        3. If either missing mtime, new replaces old (fallback)
        """
        old_mtime = old_event.metadata.get("mtime")
        new_mtime = new_event.metadata.get("mtime")

        if old_mtime is not None and new_mtime is not None:
            if new_mtime < old_mtime:
                return False  # Keep old (more recent file state)
            if new_mtime == old_mtime:
                return new_event.timestamp > old_event.timestamp

        return True  # Default: new replaces old


def get_priority(event_type: str) -> Priority:
    """Get priority for an event type."""
    for rule in PRIORITY_RULES:
        if rule.event_type == event_type:
            return rule.priority
    return Priority.NORMAL


def get_priority_reason(event_type: str) -> str:
    """Get the reason why an event type has its priority."""
    for rule in PRIORITY_RULES:
        if rule.event_type == event_type:
            return rule.reason
    return "Default priority"
