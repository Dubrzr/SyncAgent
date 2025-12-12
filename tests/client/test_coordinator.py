"""Tests for sync coordinator."""

from __future__ import annotations

import time
from typing import TYPE_CHECKING

from syncagent.client.sync.coordinator import (
    CoordinatorState,
    SyncCoordinator,
    TransferState,
    TransferStatus,
    TransferType,
)
from syncagent.client.sync.queue import EventQueue
from syncagent.client.sync.types import (
    ConflictType,
    SyncEvent,
    SyncEventSource,
    SyncEventType,
)

if TYPE_CHECKING:
    from collections.abc import Callable


class MockWorker:
    """Mock worker for testing."""

    def __init__(
        self,
        success: bool = True,
        delay: float = 0.0,
        on_execute: Callable[[SyncEvent], None] | None = None,
    ) -> None:
        self.success = success
        self.delay = delay
        self.on_execute = on_execute
        self.executed: list[SyncEvent] = []
        self.cancel_checks: list[bool] = []

    def execute(
        self,
        event: SyncEvent,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        self.executed.append(event)

        if self.on_execute:
            self.on_execute(event)

        # Simulate work with cancellation checks
        if self.delay > 0:
            steps = int(self.delay / 0.05)
            for i in range(steps):
                time.sleep(0.05)
                if cancel_check and cancel_check():
                    self.cancel_checks.append(True)
                    return False
                if on_progress:
                    on_progress(i + 1, steps)

        if cancel_check:
            self.cancel_checks.append(cancel_check())

        return self.success


class TestTransferState:
    """Tests for TransferState."""

    def test_create_transfer_state(self) -> None:
        """Should create transfer state with defaults."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        state = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
        )

        assert state.path == "test.txt"
        assert state.transfer_type == TransferType.UPLOAD
        assert state.status == TransferStatus.IN_PROGRESS
        assert not state.cancel_requested
        assert state.error is None

    def test_request_cancel(self) -> None:
        """Should set cancel_requested flag."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        state = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
        )

        assert not state.cancel_requested
        state.request_cancel()
        assert state.cancel_requested

    def test_transfer_state_with_base_version(self) -> None:
        """Should track base version for in-flight transfers (Phase 15.7)."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        state = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
            base_version=5,
        )

        assert state.base_version == 5
        assert state.detected_server_version is None
        assert state.conflict_type is None

    def test_set_conflict(self) -> None:
        """Should set conflict info and auto-cancel (Phase 15.7)."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        state = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
            base_version=3,
        )

        assert not state.cancel_requested
        state.set_conflict(ConflictType.PRE_TRANSFER, detected_version=5)

        assert state.conflict_type == ConflictType.PRE_TRANSFER
        assert state.detected_server_version == 5
        assert state.cancel_requested  # Auto-cancelled

    def test_set_conflict_concurrent_event(self) -> None:
        """Should handle concurrent event conflict (Phase 15.7)."""
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        state = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
            base_version=2,
        )

        state.set_conflict(ConflictType.CONCURRENT_EVENT, detected_version=4)

        assert state.conflict_type == ConflictType.CONCURRENT_EVENT
        assert state.detected_server_version == 4
        assert state.cancel_requested


class TestSyncCoordinator:
    """Tests for SyncCoordinator."""

    def test_start_stop(self) -> None:
        """Should start and stop coordinator."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        assert coordinator.state == CoordinatorState.STOPPED

        coordinator.start()
        assert coordinator.state == CoordinatorState.RUNNING

        coordinator.stop()
        assert coordinator.state == CoordinatorState.STOPPED

    def test_double_start(self) -> None:
        """Should handle double start gracefully."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        coordinator.start()
        coordinator.start()  # Should not raise
        assert coordinator.state == CoordinatorState.RUNNING

        coordinator.stop()

    def test_register_worker(self) -> None:
        """Should register workers."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()

        coordinator.register_worker(TransferType.UPLOAD, worker)
        # No direct way to check, but should not raise

    def test_process_upload_event(self) -> None:
        """Should dispatch upload events to upload worker."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.UPLOAD, worker)

        coordinator.start()

        # Add upload event
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        # Wait for processing
        time.sleep(0.2)
        coordinator.stop()

        assert len(worker.executed) == 1
        assert worker.executed[0].path == "test.txt"
        assert coordinator.stats.uploads_completed == 1

    def test_process_download_event(self) -> None:
        """Should dispatch download events to download worker."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.DOWNLOAD, worker)

        coordinator.start()

        # Add download event
        event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE
        )
        queue.put(event)

        # Wait for processing
        time.sleep(0.2)
        coordinator.stop()

        assert len(worker.executed) == 1
        assert coordinator.stats.downloads_completed == 1

    def test_process_delete_event(self) -> None:
        """Should dispatch delete events to delete worker."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.DELETE, worker)

        coordinator.start()

        # Add delete event
        event = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        # Wait for processing
        time.sleep(0.2)
        coordinator.stop()

        assert len(worker.executed) == 1
        assert coordinator.stats.deletes_completed == 1

    def test_no_worker_registered(self) -> None:
        """Should handle missing worker gracefully."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        # Don't register any workers

        coordinator.start()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        time.sleep(0.2)
        coordinator.stop()

        # Should not crash, event processed but no upload
        assert coordinator.stats.events_processed == 1
        assert coordinator.stats.uploads_completed == 0

    def test_worker_failure(self) -> None:
        """Should handle worker failures."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker(success=False)
        coordinator.register_worker(TransferType.UPLOAD, worker)

        coordinator.start()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        time.sleep(0.2)
        coordinator.stop()

        assert coordinator.stats.errors == 1
        assert coordinator.stats.uploads_completed == 0

    def test_get_transfer_after_complete(self) -> None:
        """Should return transfer state even after completion."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.UPLOAD, worker)

        coordinator.start()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        # Wait for processing
        time.sleep(0.2)
        coordinator.stop()

        # Transfer should exist with completed status
        transfer = coordinator.get_transfer("test.txt")
        assert transfer is not None
        assert transfer.status == TransferStatus.COMPLETED
        assert transfer.path == "test.txt"

    def test_get_active_transfers_empty_after_complete(self) -> None:
        """Should have no active transfers after all complete."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.UPLOAD, worker)

        coordinator.start()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "file0.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        # Wait for processing
        time.sleep(0.2)
        coordinator.stop()

        # No transfers should be active (all completed)
        active = coordinator.get_active_transfers()
        assert len(active) == 0

    def test_cancel_transfer_request(self) -> None:
        """Should mark cancel_requested on transfer state."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Manually add a transfer to test cancel
        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=event,
        )
        coordinator._transfers["test.txt"] = transfer

        # Cancel should succeed and set the flag
        result = coordinator.cancel_transfer("test.txt")
        assert result is True
        assert transfer.cancel_requested is True

    def test_cancel_nonexistent(self) -> None:
        """Should return False when cancelling nonexistent transfer."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        result = coordinator.cancel_transfer("nonexistent.txt")
        assert result is False

    def test_transfer_complete_callback(self) -> None:
        """Should call completion callback."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        worker = MockWorker()
        coordinator.register_worker(TransferType.UPLOAD, worker)

        completed: list[TransferState] = []
        coordinator.set_on_transfer_complete(lambda t: completed.append(t))

        coordinator.start()

        event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        queue.put(event)

        time.sleep(0.2)
        coordinator.stop()

        assert len(completed) == 1
        assert completed[0].status == TransferStatus.COMPLETED

    def test_stats(self) -> None:
        """Should track statistics."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)
        coordinator.register_worker(TransferType.UPLOAD, MockWorker())
        coordinator.register_worker(TransferType.DOWNLOAD, MockWorker())
        coordinator.register_worker(TransferType.DELETE, MockWorker())

        coordinator.start()

        # Add various events
        queue.put(SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "a.txt", SyncEventSource.LOCAL
        ))
        queue.put(SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "b.txt", SyncEventSource.REMOTE
        ))
        queue.put(SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "c.txt", SyncEventSource.LOCAL
        ))

        time.sleep(0.3)
        coordinator.stop()

        stats = coordinator.stats
        assert stats.events_processed == 3
        assert stats.uploads_completed == 1
        assert stats.downloads_completed == 1
        assert stats.deletes_completed == 1


class TestDecisionMatrix:
    """Tests for the decision matrix (concurrent event handling).

    These are unit tests that directly test _handle_concurrent by
    manually setting up transfer state. Integration testing of
    concurrent events requires Phase 15.3 (worker pool).
    """

    def test_local_modified_during_download(self) -> None:
        """LOCAL_MODIFIED during DOWNLOAD should cancel download and requeue."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Simulate an in-progress download by manually adding a transfer
        download_event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE
        )
        existing_transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.DOWNLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=download_event,
        )
        coordinator._transfers["test.txt"] = existing_transfer

        # New local modification event
        local_event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )

        # Call _handle_concurrent directly
        coordinator._handle_concurrent(local_event, existing_transfer)

        # Should have requested cancellation
        assert existing_transfer.cancel_requested is True
        assert coordinator.stats.transfers_cancelled == 1

        # Should have re-queued the local event
        assert queue.has_event("test.txt")

    def test_remote_modified_during_upload(self) -> None:
        """REMOTE_MODIFIED during UPLOAD should detect conflict."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        conflicts: list[tuple[str, SyncEvent, SyncEvent]] = []
        coordinator.set_on_conflict(
            lambda path, local, remote: conflicts.append((path, local, remote))
        )

        # Simulate an in-progress upload with base_version
        upload_event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        existing_transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=upload_event,
            base_version=2,  # Phase 15.7: track base version
        )
        coordinator._transfers["test.txt"] = existing_transfer

        # New remote modification event with server version
        remote_event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE,
            metadata={"version": 4},  # Server is now at version 4
        )

        # Call _handle_concurrent directly
        coordinator._handle_concurrent(remote_event, existing_transfer)

        # Should detect conflict
        assert coordinator.stats.conflicts_detected == 1
        assert len(conflicts) == 1
        assert conflicts[0][0] == "test.txt"

        # Phase 15.7: Should have conflict type set
        assert existing_transfer.conflict_type == ConflictType.CONCURRENT_EVENT
        assert existing_transfer.detected_server_version == 4
        # Now auto-cancels on conflict
        assert existing_transfer.cancel_requested is True

    def test_local_deleted_during_download(self) -> None:
        """LOCAL_DELETED during DOWNLOAD should cancel download."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Simulate an in-progress download
        download_event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE
        )
        existing_transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.DOWNLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=download_event,
        )
        coordinator._transfers["test.txt"] = existing_transfer

        # New local delete event
        delete_event = SyncEvent.create(
            SyncEventType.LOCAL_DELETED, "test.txt", SyncEventSource.LOCAL
        )

        # Call _handle_concurrent directly
        coordinator._handle_concurrent(delete_event, existing_transfer)

        # Should have requested cancellation
        assert existing_transfer.cancel_requested is True
        assert coordinator.stats.transfers_cancelled == 1

    def test_local_event_during_upload_ignored(self) -> None:
        """LOCAL_* during UPLOAD should be ignored (upload continues)."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Simulate an in-progress upload
        upload_event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )
        existing_transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=upload_event,
        )
        coordinator._transfers["test.txt"] = existing_transfer

        # Another local modification
        local_event = SyncEvent.create(
            SyncEventType.LOCAL_MODIFIED, "test.txt", SyncEventSource.LOCAL
        )

        # Call _handle_concurrent
        coordinator._handle_concurrent(local_event, existing_transfer)

        # Should NOT cancel or conflict - just ignore
        assert existing_transfer.cancel_requested is False
        assert coordinator.stats.transfers_cancelled == 0
        assert coordinator.stats.conflicts_detected == 0

    def test_remote_event_during_download_ignored(self) -> None:
        """REMOTE_* during DOWNLOAD should be ignored (newer version coming)."""
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Simulate an in-progress download
        download_event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE
        )
        existing_transfer = TransferState(
            path="test.txt",
            transfer_type=TransferType.DOWNLOAD,
            status=TransferStatus.IN_PROGRESS,
            event=download_event,
        )
        coordinator._transfers["test.txt"] = existing_transfer

        # Another remote modification (newer version available)
        remote_event = SyncEvent.create(
            SyncEventType.REMOTE_MODIFIED, "test.txt", SyncEventSource.REMOTE
        )

        # Call _handle_concurrent
        coordinator._handle_concurrent(remote_event, existing_transfer)

        # Should NOT cancel - download continues with current version
        assert existing_transfer.cancel_requested is False
        assert coordinator.stats.transfers_cancelled == 0
