"""Tests for sync event queue module."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest

from syncagent.client.sync.queue import (
    EventQueue,
    SyncEvent,
    SyncEventSource,
    SyncEventType,
)


class TestSyncEventType:
    """Tests for SyncEventType enum."""

    def test_priority_order(self) -> None:
        """DELETE events should have higher priority (lower value) than others."""
        assert SyncEventType.LOCAL_DELETED < SyncEventType.LOCAL_CREATED
        assert SyncEventType.LOCAL_DELETED < SyncEventType.REMOTE_CREATED
        assert SyncEventType.REMOTE_DELETED < SyncEventType.REMOTE_MODIFIED
        assert SyncEventType.LOCAL_MODIFIED < SyncEventType.REMOTE_MODIFIED
        assert SyncEventType.TRANSFER_COMPLETE > SyncEventType.REMOTE_MODIFIED

    def test_all_types_defined(self) -> None:
        """All expected event types should be defined."""
        expected = {
            "LOCAL_CREATED",
            "LOCAL_MODIFIED",
            "LOCAL_DELETED",
            "REMOTE_CREATED",
            "REMOTE_MODIFIED",
            "REMOTE_DELETED",
            "TRANSFER_COMPLETE",
            "TRANSFER_FAILED",
        }
        actual = {t.name for t in SyncEventType}
        assert actual == expected


class TestSyncEvent:
    """Tests for SyncEvent dataclass."""

    def test_create_event(self) -> None:
        """Test creating an event with factory method."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test/file.txt",
            source=SyncEventSource.LOCAL,
        )

        assert event.event_type == SyncEventType.LOCAL_MODIFIED
        assert event.path == "test/file.txt"
        assert event.source == SyncEventSource.LOCAL
        assert event.priority == int(SyncEventType.LOCAL_MODIFIED)
        assert event.timestamp > 0
        assert event.event_id
        assert event.metadata == {}

    def test_create_event_with_metadata(self) -> None:
        """Test creating an event with metadata."""
        metadata = {"version": 5, "hash": "abc123"}
        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_MODIFIED,
            path="docs/readme.md",
            source=SyncEventSource.REMOTE,
            metadata=metadata,
        )

        assert event.metadata == metadata
        assert event.metadata["version"] == 5

    def test_event_ordering(self) -> None:
        """Events should be ordered by priority then timestamp."""
        time.sleep(0.01)  # Ensure different timestamps
        event1 = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "a.txt", SyncEventSource.REMOTE
        )
        time.sleep(0.01)
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "b.txt", SyncEventSource.LOCAL
        )
        time.sleep(0.01)
        event3 = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "c.txt", SyncEventSource.LOCAL
        )

        # event2 and event3 (DELETE) should come before event1 (MODIFIED)
        sorted_events = sorted([event1, event2, event3])
        assert sorted_events[0] == event2  # First DELETE (earlier)
        assert sorted_events[1] == event3  # Second DELETE (later)
        assert sorted_events[2] == event1  # MODIFIED (lowest priority)

    def test_event_repr(self) -> None:
        """Test string representation."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_CREATED, "new.txt", SyncEventSource.LOCAL
        )
        repr_str = repr(event)
        assert "LOCAL_CREATED" in repr_str
        assert "new.txt" in repr_str
        assert "LOCAL" in repr_str


class TestEventQueue:
    """Tests for EventQueue class."""

    def test_put_and_get(self) -> None:
        """Test basic put and get operations."""
        queue = EventQueue()
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )

        assert queue.put(event)
        assert len(queue) == 1

        retrieved = queue.get(timeout=1)
        assert retrieved == event
        assert len(queue) == 0

    def test_priority_ordering(self) -> None:
        """Events should be retrieved in priority order."""
        queue = EventQueue()

        # Add events in wrong priority order
        event_download = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "download.txt", SyncEventSource.REMOTE
        )
        event_upload = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "upload.txt", SyncEventSource.LOCAL
        )
        event_delete = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "delete.txt", SyncEventSource.LOCAL
        )

        queue.put(event_download)
        queue.put(event_upload)
        queue.put(event_delete)

        # Should get them in priority order: DELETE, UPLOAD (LOCAL), DOWNLOAD (REMOTE)
        assert queue.get(timeout=1) == event_delete
        assert queue.get(timeout=1) == event_upload
        assert queue.get(timeout=1) == event_download

    def test_deduplication(self) -> None:
        """Only the latest event per path should be kept."""
        queue = EventQueue()

        event1 = SyncEvent.create(
            SyncEventType.LOCAL_CREATED, "file.txt", SyncEventSource.LOCAL
        )
        time.sleep(0.01)
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file.txt", SyncEventSource.LOCAL
        )
        time.sleep(0.01)
        event3 = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "file.txt", SyncEventSource.LOCAL
        )

        queue.put(event1)
        assert len(queue) == 1
        queue.put(event2)
        assert len(queue) == 1  # Replaced, not added
        queue.put(event3)
        assert len(queue) == 1  # Replaced, not added

        # Should get the latest event
        retrieved = queue.get(timeout=1)
        assert retrieved == event3

    def test_get_nowait(self) -> None:
        """get_nowait should return None if queue is empty."""
        queue = EventQueue()
        assert queue.get_nowait() is None

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)
        assert queue.get_nowait() == event
        assert queue.get_nowait() is None

    def test_get_timeout(self) -> None:
        """get should return None after timeout if queue is empty."""
        queue = EventQueue()
        start = time.time()
        result = queue.get(timeout=0.1)
        elapsed = time.time() - start

        assert result is None
        assert elapsed >= 0.1
        assert elapsed < 0.3

    def test_peek(self) -> None:
        """peek should return event without removing it."""
        queue = EventQueue()
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        assert queue.peek() == event
        assert len(queue) == 1  # Still there
        assert queue.peek() == event  # Can peek multiple times

    def test_remove(self) -> None:
        """remove should remove event by path."""
        queue = EventQueue()
        event1 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "keep.txt", SyncEventSource.LOCAL
        )
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "remove.txt", SyncEventSource.LOCAL
        )

        queue.put(event1)
        queue.put(event2)
        assert len(queue) == 2

        removed = queue.remove("remove.txt")
        assert removed == event2
        assert len(queue) == 1
        assert queue.remove("remove.txt") is None  # Already removed

    def test_has_event(self) -> None:
        """has_event should check if path has pending event."""
        queue = EventQueue()
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )

        assert not queue.has_event("test.txt")
        queue.put(event)
        assert queue.has_event("test.txt")
        assert not queue.has_event("other.txt")

    def test_get_event(self) -> None:
        """get_event should return event without removing."""
        queue = EventQueue()
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        assert queue.get_event("test.txt") == event
        assert len(queue) == 1  # Not removed
        assert queue.get_event("other.txt") is None

    def test_clear(self) -> None:
        """clear should remove all events."""
        queue = EventQueue()
        for i in range(5):
            event = SyncEvent.create(
                SyncEventType.LOCAL_MODIFIED, f"file{i}.txt", SyncEventSource.LOCAL
            )
            queue.put(event)

        assert len(queue) == 5
        count = queue.clear()
        assert count == 5
        assert len(queue) == 0

    def test_max_size(self) -> None:
        """Queue should respect max_size."""
        queue = EventQueue(max_size=2)

        event1 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file1.txt", SyncEventSource.LOCAL
        )
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file2.txt", SyncEventSource.LOCAL
        )
        event3 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file3.txt", SyncEventSource.LOCAL
        )

        assert queue.put(event1)
        assert queue.put(event2)
        assert not queue.put(event3)  # Should be rejected
        assert len(queue) == 2

    def test_max_size_allows_update(self) -> None:
        """max_size should allow updates to existing paths."""
        queue = EventQueue(max_size=2)

        event1 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file1.txt", SyncEventSource.LOCAL
        )
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file2.txt", SyncEventSource.LOCAL
        )
        event1_update = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "file1.txt", SyncEventSource.LOCAL
        )

        queue.put(event1)
        queue.put(event2)
        assert queue.put(event1_update)  # Update should work
        assert len(queue) == 2

    def test_iteration(self) -> None:
        """Queue should be iterable in priority order."""
        queue = EventQueue()
        event1 = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "low.txt", SyncEventSource.REMOTE
        )
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "high.txt", SyncEventSource.LOCAL
        )

        queue.put(event1)
        queue.put(event2)

        events = list(queue)
        assert len(events) == 2
        assert events[0] == event2  # DELETE first
        assert events[1] == event1
        assert len(queue) == 2  # Not removed by iteration

    def test_bool(self) -> None:
        """Queue should be falsy when empty."""
        queue = EventQueue()
        assert not queue

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)
        assert queue

    def test_stats(self) -> None:
        """stats should return event counts by type."""
        queue = EventQueue()
        queue.put(
            SyncEvent.create(
                SyncEventType.LOCAL_MODIFIED, "a.txt", SyncEventSource.LOCAL
            )
        )
        queue.put(
            SyncEvent.create(
                SyncEventType.LOCAL_MODIFIED, "b.txt", SyncEventSource.LOCAL
            )
        )
        queue.put(
            SyncEvent.create(
                SyncEventType.LOCAL_DELETED, "c.txt", SyncEventSource.LOCAL
            )
        )
        queue.put(
            SyncEvent.create(
                SyncEventType.REMOTE_MODIFIED, "d.txt", SyncEventSource.REMOTE
            )
        )

        stats = queue.stats()
        assert stats["total"] == 4
        assert stats["local_modified"] == 2
        assert stats["local_deleted"] == 1
        assert stats["remote_modified"] == 1

    def test_close(self) -> None:
        """close should wake up waiting threads."""
        queue = EventQueue()

        def wait_for_event() -> SyncEvent | None:
            try:
                return queue.get(timeout=10)
            except RuntimeError:
                return None

        thread = threading.Thread(target=wait_for_event)
        thread.start()
        time.sleep(0.1)  # Let thread start waiting

        queue.close()
        thread.join(timeout=1)
        assert not thread.is_alive()
        assert queue.is_closed

    def test_put_after_close(self) -> None:
        """put should raise after close."""
        queue = EventQueue()
        queue.close()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        with pytest.raises(RuntimeError, match="closed"):
            queue.put(event)


class TestEventQueueThreadSafety:
    """Tests for thread safety of EventQueue."""

    def test_concurrent_puts(self) -> None:
        """Multiple threads should be able to put events safely."""
        queue = EventQueue()
        num_threads = 10
        events_per_thread = 100

        def put_events(thread_id: int) -> None:
            for i in range(events_per_thread):
                event = SyncEvent.create(
                    SyncEventType.LOCAL_MODIFIED,
                    f"thread{thread_id}_file{i}.txt",
                    SyncEventSource.LOCAL,
                )
                queue.put(event)

        threads = [
            threading.Thread(target=put_events, args=(i,)) for i in range(num_threads)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Each thread adds unique paths
        assert len(queue) == num_threads * events_per_thread

    def test_concurrent_put_get(self) -> None:
        """Producer and consumer threads should work correctly."""
        queue = EventQueue()
        num_events = 100
        received: list[SyncEvent] = []
        lock = threading.Lock()

        def producer() -> None:
            for i in range(num_events):
                event = SyncEvent.create(
                    SyncEventType.LOCAL_MODIFIED,
                    f"file{i}.txt",
                    SyncEventSource.LOCAL,
                )
                queue.put(event)
                time.sleep(0.001)

        def consumer() -> None:
            while True:
                event = queue.get(timeout=0.5)
                if event is None:
                    break
                with lock:
                    received.append(event)

        producer_thread = threading.Thread(target=producer)
        consumer_thread = threading.Thread(target=consumer)

        producer_thread.start()
        consumer_thread.start()

        producer_thread.join()
        consumer_thread.join()

        assert len(received) == num_events


class TestEventQueuePersistence:
    """Tests for EventQueue SQLite persistence."""

    def test_persistence_save_and_load(self, tmp_path: Path) -> None:
        """Events should be saved to SQLite and loaded on restart."""
        db_path = tmp_path / "queue.db"

        # Create queue and add events
        queue1 = EventQueue(persistence_path=db_path)
        event1 = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED,
            "file1.txt",
            SyncEventSource.LOCAL,
            metadata={"size": 1024},
        )
        event2 = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED,
            "file2.txt",
            SyncEventSource.REMOTE,
            metadata={"version": 5},
        )
        queue1.put(event1)
        queue1.put(event2)
        queue1.close()

        # Create new queue with same DB - should load events
        queue2 = EventQueue(persistence_path=db_path)
        assert len(queue2) == 2

        # Verify events are correct
        loaded1 = queue2.get_event("file1.txt")
        loaded2 = queue2.get_event("file2.txt")

        assert loaded1 is not None
        assert loaded1.event_type == SyncEventType.LOCAL_MODIFIED
        assert loaded1.metadata["size"] == 1024

        assert loaded2 is not None
        assert loaded2.event_type == SyncEventType.REMOTE_MODIFIED
        assert loaded2.metadata["version"] == 5

        queue2.close()

    def test_persistence_remove(self, tmp_path: Path) -> None:
        """Removed events should be deleted from SQLite."""
        db_path = tmp_path / "queue.db"

        queue1 = EventQueue(persistence_path=db_path)
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file.txt", SyncEventSource.LOCAL
        )
        queue1.put(event)
        queue1.get(timeout=1)  # Remove by getting
        queue1.close()

        # Should be empty on reload
        queue2 = EventQueue(persistence_path=db_path)
        assert len(queue2) == 0
        queue2.close()

    def test_persistence_clear(self, tmp_path: Path) -> None:
        """Clear should delete all events from SQLite."""
        db_path = tmp_path / "queue.db"

        queue1 = EventQueue(persistence_path=db_path)
        for i in range(5):
            event = SyncEvent.create(
                SyncEventType.LOCAL_MODIFIED, f"file{i}.txt", SyncEventSource.LOCAL
            )
            queue1.put(event)
        queue1.clear()
        queue1.close()

        # Should be empty on reload
        queue2 = EventQueue(persistence_path=db_path)
        assert len(queue2) == 0
        queue2.close()

    def test_persistence_deduplication(self, tmp_path: Path) -> None:
        """Deduplication should update SQLite correctly."""
        db_path = tmp_path / "queue.db"

        queue1 = EventQueue(persistence_path=db_path)
        event1 = SyncEvent.create(
            SyncEventType.LOCAL_CREATED, "file.txt", SyncEventSource.LOCAL
        )
        event2 = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "file.txt", SyncEventSource.LOCAL
        )
        queue1.put(event1)
        queue1.put(event2)  # Should replace
        queue1.close()

        # Should load the latest event
        queue2 = EventQueue(persistence_path=db_path)
        assert len(queue2) == 1
        loaded = queue2.get_event("file.txt")
        assert loaded is not None
        assert loaded.event_type == SyncEventType.LOCAL_DELETED
        queue2.close()
