"""Event queue system for sync coordination.

This module provides:
- SyncEventType: Enum of all possible sync events
- SyncEventSource: Enum for event origin (local/remote)
- SyncEvent: Dataclass representing a sync event
- EventQueue: Thread-safe priority queue with deduplication

The queue enables the coordinator to process events in optimal order:
- DELETE events have highest priority (avoid useless transfers)
- UPLOAD events come next (local changes take precedence)
- DOWNLOAD events have lowest priority

Events are deduplicated by path - only the most recent event per path is kept.

Usage with FileWatcher:
    queue = EventQueue()
    watcher = FileWatcher(watch_path, event_queue=queue)
    watcher.start()
    # Events are automatically injected into the queue
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field
from enum import IntEnum, auto
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


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


class EventQueue:
    """Thread-safe priority queue with path-based deduplication.

    Events are stored in priority order (lowest priority value first).
    When a new event arrives for a path that already has a pending event,
    the old event is replaced with the new one.

    Attributes:
        max_size: Maximum queue size (0 = unlimited)
        persistence_path: Optional SQLite path for persistence
    """

    def __init__(
        self,
        max_size: int = 0,
        persistence_path: Path | None = None,
    ) -> None:
        """Initialize the event queue.

        Args:
            max_size: Maximum number of events (0 = unlimited)
            persistence_path: Optional path to SQLite DB for persistence
        """
        self._lock = threading.RLock()
        self._not_empty = threading.Condition(self._lock)
        self._events: dict[str, SyncEvent] = {}  # path -> event
        self._max_size = max_size
        self._persistence_path = persistence_path
        self._db: sqlite3.Connection | None = None
        self._closed = False

        if persistence_path:
            self._init_persistence()
            self._load_from_persistence()

    def _init_persistence(self) -> None:
        """Initialize SQLite database for persistence."""
        if not self._persistence_path:
            return

        self._persistence_path.parent.mkdir(parents=True, exist_ok=True)
        self._db = sqlite3.connect(
            str(self._persistence_path),
            check_same_thread=False,
        )
        self._db.execute("""
            CREATE TABLE IF NOT EXISTS sync_events (
                path TEXT PRIMARY KEY,
                event_type INTEGER NOT NULL,
                source INTEGER NOT NULL,
                timestamp REAL NOT NULL,
                event_id TEXT NOT NULL,
                metadata TEXT NOT NULL
            )
        """)
        self._db.commit()
        logger.debug("Initialized event queue persistence at %s", self._persistence_path)

    def _load_from_persistence(self) -> None:
        """Load events from SQLite on startup."""
        if not self._db:
            return

        import json

        cursor = self._db.execute(
            "SELECT path, event_type, source, timestamp, event_id, metadata FROM sync_events"
        )
        count = 0
        for row in cursor:
            path, event_type, source, timestamp, event_id, metadata_json = row
            event = SyncEvent(
                priority=event_type,
                timestamp=timestamp,
                event_type=SyncEventType(event_type),
                path=path,
                source=SyncEventSource(source),
                event_id=event_id,
                metadata=json.loads(metadata_json),
            )
            self._events[path] = event
            count += 1

        if count > 0:
            logger.info("Loaded %d pending events from persistence", count)

    def _persist_event(self, event: SyncEvent) -> None:
        """Save an event to SQLite."""
        if not self._db:
            return

        import json

        self._db.execute(
            """
            INSERT OR REPLACE INTO sync_events
            (path, event_type, source, timestamp, event_id, metadata)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                event.path,
                int(event.event_type),
                int(event.source),
                event.timestamp,
                event.event_id,
                json.dumps(event.metadata),
            ),
        )
        self._db.commit()

    def _remove_from_persistence(self, path: str) -> None:
        """Remove an event from SQLite."""
        if not self._db:
            return

        self._db.execute("DELETE FROM sync_events WHERE path = ?", (path,))
        self._db.commit()

    def put(self, event: SyncEvent) -> bool:
        """Add or update an event in the queue.

        If an event for this path already exists, it is replaced.
        This implements deduplication - only the latest event per path is kept.

        Args:
            event: The event to add

        Returns:
            True if event was added, False if queue is full

        Raises:
            RuntimeError: If queue is closed
        """
        with self._lock:
            if self._closed:
                raise RuntimeError("Queue is closed")

            # Check max size (only for new paths)
            if (
                self._max_size > 0
                and event.path not in self._events
                and len(self._events) >= self._max_size
            ):
                logger.warning(
                    "Event queue full (max_size=%d), dropping event: %s",
                    self._max_size,
                    event,
                )
                return False

            # Deduplication: replace existing event for this path
            old_event = self._events.get(event.path)
            if old_event:
                logger.debug(
                    "Replacing event for %s: %s -> %s",
                    event.path,
                    old_event.event_type.name,
                    event.event_type.name,
                )

            self._events[event.path] = event
            self._persist_event(event)
            self._not_empty.notify()

            logger.debug("Queued event: %s (queue size: %d)", event, len(self._events))
            return True

    def get(self, timeout: float | None = None) -> SyncEvent | None:
        """Get the highest priority event from the queue.

        Blocks until an event is available or timeout expires.

        Args:
            timeout: Maximum seconds to wait (None = wait forever)

        Returns:
            The highest priority event, or None if timeout expired

        Raises:
            RuntimeError: If queue is closed while waiting
        """
        with self._not_empty:
            # Wait for an event
            deadline = None if timeout is None else time.time() + timeout

            while not self._events and not self._closed:
                if deadline is not None:
                    remaining = deadline - time.time()
                    if remaining <= 0:
                        return None
                    self._not_empty.wait(timeout=remaining)
                else:
                    self._not_empty.wait()

            if self._closed and not self._events:
                raise RuntimeError("Queue is closed")

            if not self._events:
                return None

            # Get highest priority event (lowest priority value)
            path = min(self._events, key=lambda p: self._events[p])
            event = self._events.pop(path)
            self._remove_from_persistence(path)

            logger.debug("Dequeued event: %s (queue size: %d)", event, len(self._events))
            return event

    def get_nowait(self) -> SyncEvent | None:
        """Get event without blocking.

        Returns:
            The highest priority event, or None if queue is empty
        """
        return self.get(timeout=0)

    def peek(self) -> SyncEvent | None:
        """Look at the highest priority event without removing it.

        Returns:
            The highest priority event, or None if queue is empty
        """
        with self._lock:
            if not self._events:
                return None
            path = min(self._events, key=lambda p: self._events[p])
            return self._events[path]

    def remove(self, path: str) -> SyncEvent | None:
        """Remove an event by path.

        Useful when a transfer is cancelled and we need to remove pending events.

        Args:
            path: The file path to remove

        Returns:
            The removed event, or None if not found
        """
        with self._lock:
            event = self._events.pop(path, None)
            if event:
                self._remove_from_persistence(path)
                logger.debug("Removed event for path: %s", path)
            return event

    def has_event(self, path: str) -> bool:
        """Check if there's a pending event for a path.

        Args:
            path: The file path to check

        Returns:
            True if an event exists for this path
        """
        with self._lock:
            return path in self._events

    def get_event(self, path: str) -> SyncEvent | None:
        """Get the pending event for a path without removing it.

        Args:
            path: The file path to look up

        Returns:
            The event for this path, or None if not found
        """
        with self._lock:
            return self._events.get(path)

    def clear(self) -> int:
        """Remove all events from the queue.

        Returns:
            Number of events removed
        """
        with self._lock:
            count = len(self._events)
            self._events.clear()
            if self._db:
                self._db.execute("DELETE FROM sync_events")
                self._db.commit()
            logger.info("Cleared %d events from queue", count)
            return count

    def close(self) -> None:
        """Close the queue and wake up waiting threads."""
        with self._lock:
            self._closed = True
            self._not_empty.notify_all()
            if self._db:
                self._db.close()
                self._db = None
            logger.debug("Event queue closed")

    def __len__(self) -> int:
        """Get number of pending events."""
        with self._lock:
            return len(self._events)

    def __iter__(self) -> Iterator[SyncEvent]:
        """Iterate over events in priority order (does not remove them)."""
        with self._lock:
            sorted_events = sorted(self._events.values())
            return iter(sorted_events)

    def __bool__(self) -> bool:
        """Check if queue has events."""
        with self._lock:
            return bool(self._events)

    @property
    def is_closed(self) -> bool:
        """Check if queue is closed."""
        return self._closed

    def stats(self) -> dict[str, int]:
        """Get queue statistics.

        Returns:
            Dictionary with event counts by type
        """
        with self._lock:
            stats: dict[str, int] = {
                "total": len(self._events),
                "local_created": 0,
                "local_modified": 0,
                "local_deleted": 0,
                "remote_created": 0,
                "remote_modified": 0,
                "remote_deleted": 0,
            }
            for event in self._events.values():
                key = event.event_type.name.lower()
                if key in stats:
                    stats[key] += 1
            return stats
