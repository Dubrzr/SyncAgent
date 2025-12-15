"""Event deduplication strategy.

This module provides mtime-aware event comparison for queue deduplication.

Note: Event priorities are defined in SyncEventType (types.py) where
the enum values themselves encode priority (10, 20, 30, 90).
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from syncagent.client.sync.types import SyncEvent


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

        # Type guard: mtime values are always floats when present
        if isinstance(old_mtime, int | float) and isinstance(new_mtime, int | float):
            if new_mtime < old_mtime:
                return False  # Keep old (more recent file state)
            if new_mtime == old_mtime:
                return new_event.timestamp > old_event.timestamp

        return True  # Default: new replaces old
