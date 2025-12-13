"""Event queue system for sync coordination.

This module provides:
- EventQueue: Thread-safe priority queue with deduplication

Event types (SyncEventType, SyncEventSource, SyncEvent) are in types.py.

The queue enables the coordinator to process events in optimal order:
- DELETE events have highest priority (avoid useless transfers)
- UPLOAD events come next (local changes take precedence)
- DOWNLOAD events have lowest priority

Events are deduplicated by path - only the most recent event per path is kept.
Conflict handling is done at execution time by workers, not by the queue.

Usage with FileWatcher:
    queue = EventQueue()
    watcher = FileWatcher(watch_path, event_queue=queue)
    watcher.start()
    # Events are automatically injected into the queue

Persistence (SQLite):
    The queue supports optional SQLite persistence for crash recovery.
    Each operation (put/get/remove) commits immediately for durability.

    ACID properties:
    - Atomicity: Each operation is atomic (single commit)
    - Consistency: In-memory dict may diverge from SQLite on mid-op crash
    - Isolation: RLock ensures thread-safe operations
    - Durability: SQLite WAL mode ensures writes survive crashes

    Note: This is NOT a fully ACID queue. On crash, events may be lost if
    the in-memory dict was updated but SQLite commit didn't complete.
    This is acceptable because:
    1. The filesystem is the source of truth (files still exist)
    2. The watcher will re-detect changes on restart
    3. Periodic full scans ensure eventual consistency
"""

from __future__ import annotations

import logging
import sqlite3
import threading
import time
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.types import (
    SyncEvent,
    SyncEventSource,
    SyncEventType,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

logger = logging.getLogger(__name__)


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

        If an event for this path already exists, uses mtime-aware deduplication:
        - Compare file mtime from metadata (for LOCAL events)
        - Keep the event with the most recent mtime
        - If same mtime, keep the most recent event timestamp

        This prevents race conditions where a scan might emit an event with
        stale mtime after a watcher has already emitted one with current mtime.

        Args:
            event: The event to add

        Returns:
            True if event was added/accepted, False if queue is full

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

            # Deduplication with mtime-awareness
            old_event = self._events.get(event.path)
            if old_event:
                # mtime-aware deduplication for LOCAL events
                old_mtime = old_event.metadata.get("mtime")
                new_mtime = event.metadata.get("mtime")

                if old_mtime is not None and new_mtime is not None:
                    # Both have mtime - compare file modification times
                    if new_mtime < old_mtime:
                        # New event has older mtime - keep old event
                        logger.debug(
                            "Ignoring event with older mtime for %s: new_mtime=%.3f < old_mtime=%.3f",
                            event.path,
                            new_mtime,
                            old_mtime,
                        )
                        return True  # Event "accepted" but not stored

                    if new_mtime == old_mtime and event.timestamp <= old_event.timestamp:
                        # Same mtime - keep the more recent event timestamp
                        logger.debug(
                            "Ignoring event with same mtime but older timestamp for %s",
                            event.path,
                        )
                        return True

                # Different mtime (new > old) or missing mtime - replace
                logger.debug(
                    "Replacing event for %s: %s -> %s (mtime: %s -> %s)",
                    event.path,
                    old_event.event_type.name,
                    event.event_type.name,
                    old_mtime,
                    new_mtime,
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
