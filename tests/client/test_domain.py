"""Tests for sync domain modules.

Tests for:
- domain/priorities.py - mtime-aware event comparison
- domain/transfers.py - Transfer state machine
- domain/decisions.py - Decision matrix
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest

from syncagent.client.sync.domain import (
    DecisionAction,
    DecisionMatrix,
    DecisionRule,
    InvalidTransitionError,
    MtimeAwareComparator,
    Transfer,
    TransferStatus,
    TransferTracker,
    TransferType,
    decide,
)
from syncagent.client.sync.types import SyncEvent, SyncEventSource, SyncEventType

# =============================================================================
# Tests for domain/priorities.py
# =============================================================================


class TestMtimeAwareComparator:
    """Test mtime-aware event comparison."""

    def create_event(
        self,
        path: str = "test.txt",
        mtime: float | None = None,
        timestamp: float | None = None,
    ) -> SyncEvent:
        """Create a test event with optional mtime and timestamp."""
        ts = timestamp or time.time()
        metadata = {"mtime": mtime} if mtime is not None else {}
        return SyncEvent(
            priority=SyncEventType.LOCAL_MODIFIED,  # Use int value from enum
            timestamp=ts,
            event_type=SyncEventType.LOCAL_MODIFIED,
            path=path,
            source=SyncEventSource.LOCAL,
            event_id=f"test-{ts}",
            metadata=metadata,
        )

    def test_newer_mtime_wins(self) -> None:
        """Event with newer mtime should replace old event."""
        comparator = MtimeAwareComparator()
        old_event = self.create_event(mtime=100.0, timestamp=1.0)
        new_event = self.create_event(mtime=200.0, timestamp=2.0)

        assert comparator.should_replace(old_event, new_event) is True

    def test_older_mtime_ignored(self) -> None:
        """Event with older mtime should NOT replace."""
        comparator = MtimeAwareComparator()
        old_event = self.create_event(mtime=200.0, timestamp=1.0)
        new_event = self.create_event(mtime=100.0, timestamp=2.0)

        assert comparator.should_replace(old_event, new_event) is False

    def test_same_mtime_uses_timestamp(self) -> None:
        """Same mtime falls back to event timestamp."""
        comparator = MtimeAwareComparator()

        old_event = self.create_event(mtime=100.0, timestamp=1.0)
        new_event = self.create_event(mtime=100.0, timestamp=2.0)
        assert comparator.should_replace(old_event, new_event) is True

        old_event = self.create_event(mtime=100.0, timestamp=2.0)
        new_event = self.create_event(mtime=100.0, timestamp=1.0)
        assert comparator.should_replace(old_event, new_event) is False

    def test_no_mtime_fallback(self) -> None:
        """Missing mtime defaults to replacement."""
        comparator = MtimeAwareComparator()

        # Neither has mtime
        old_event = self.create_event(mtime=None, timestamp=1.0)
        new_event = self.create_event(mtime=None, timestamp=2.0)
        assert comparator.should_replace(old_event, new_event) is True

        # Only old has mtime
        old_event = self.create_event(mtime=100.0, timestamp=1.0)
        new_event = self.create_event(mtime=None, timestamp=2.0)
        assert comparator.should_replace(old_event, new_event) is True

        # Only new has mtime
        old_event = self.create_event(mtime=None, timestamp=1.0)
        new_event = self.create_event(mtime=100.0, timestamp=2.0)
        assert comparator.should_replace(old_event, new_event) is True


# =============================================================================
# Tests for domain/transfers.py
# =============================================================================


class TestTransfer:
    """Test Transfer state machine."""

    def test_initial_state_is_pending(self) -> None:
        """New transfer starts as PENDING."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        assert transfer.status == TransferStatus.PENDING
        assert not transfer.is_terminal

    def test_valid_transitions(self) -> None:
        """Test valid state transitions."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)

        transfer.start()
        assert transfer.status == TransferStatus.IN_PROGRESS

        transfer.complete()
        assert transfer.status == TransferStatus.COMPLETED
        assert transfer.is_terminal

    def test_cancel_from_pending(self) -> None:
        """Can cancel from PENDING."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        transfer.cancel()
        assert transfer.status == TransferStatus.CANCELLED
        assert transfer.is_terminal

    def test_cancel_from_in_progress(self) -> None:
        """Can cancel from IN_PROGRESS."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        transfer.start()
        transfer.cancel()
        assert transfer.status == TransferStatus.CANCELLED

    def test_invalid_transition_raises(self) -> None:
        """Invalid transitions raise InvalidTransitionError."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)

        # Can't go directly from PENDING to COMPLETED
        with pytest.raises(InvalidTransitionError):
            transfer.transition_to(TransferStatus.COMPLETED)

    def test_cannot_transition_from_terminal(self) -> None:
        """Cannot transition from terminal states."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        transfer.start()
        transfer.complete()

        with pytest.raises(InvalidTransitionError):
            transfer.transition_to(TransferStatus.IN_PROGRESS)

    def test_fail_transition(self) -> None:
        """Test fail() method."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        transfer.start()
        transfer.fail(Exception("Test error"))

        assert transfer.status == TransferStatus.FAILED
        assert transfer.is_terminal

    def test_mark_conflict(self) -> None:
        """Test marking conflict info."""
        transfer = Transfer(path="test.txt", transfer_type=TransferType.UPLOAD)
        assert not transfer.has_conflict

        transfer.mark_conflict("VERSION_MISMATCH", 5)

        assert transfer.has_conflict
        assert transfer.conflict_type == "VERSION_MISMATCH"
        assert transfer.detected_server_version == 5

    def test_callbacks_on_complete(self) -> None:
        """Test on_complete callback."""
        callback = MagicMock()
        transfer = Transfer(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            _on_complete=callback,
        )
        transfer.start()
        transfer.complete()

        callback.assert_called_once_with(transfer)

    def test_callbacks_on_error(self) -> None:
        """Test on_error callback."""
        callback = MagicMock()
        error = Exception("Test error")
        transfer = Transfer(
            path="test.txt",
            transfer_type=TransferType.UPLOAD,
            _on_error=callback,
        )
        transfer.start()
        transfer.fail(error)

        callback.assert_called_once_with(transfer, error)


class TestTransferTracker:
    """Test TransferTracker."""

    def test_create_and_get(self) -> None:
        """Can create and retrieve transfers."""
        tracker = TransferTracker()
        transfer = tracker.create("test.txt", TransferType.UPLOAD)

        assert tracker.get("test.txt") is transfer
        assert "test.txt" in tracker

    def test_get_active(self) -> None:
        """get_active only returns non-terminal transfers."""
        tracker = TransferTracker()
        transfer = tracker.create("test.txt", TransferType.UPLOAD)

        assert tracker.get_active("test.txt") is transfer

        transfer.start()
        transfer.complete()

        assert tracker.get_active("test.txt") is None
        assert tracker.get("test.txt") is transfer  # Still retrievable

    def test_all_active(self) -> None:
        """all_active returns only non-terminal transfers."""
        tracker = TransferTracker()
        t1 = tracker.create("a.txt", TransferType.UPLOAD)
        t2 = tracker.create("b.txt", TransferType.DOWNLOAD)
        t3 = tracker.create("c.txt", TransferType.DELETE)

        t1.start()
        t1.complete()

        active = tracker.all_active()
        assert t1 not in active
        assert t2 in active
        assert t3 in active

    def test_cancel_all(self) -> None:
        """cancel_all cancels all active transfers."""
        tracker = TransferTracker()
        t1 = tracker.create("a.txt", TransferType.UPLOAD)
        t2 = tracker.create("b.txt", TransferType.DOWNLOAD)

        tracker.cancel_all()

        assert t1.status == TransferStatus.CANCELLED
        assert t2.status == TransferStatus.CANCELLED

    def test_remove(self) -> None:
        """Can remove transfers."""
        tracker = TransferTracker()
        tracker.create("test.txt", TransferType.UPLOAD)

        assert "test.txt" in tracker
        tracker.remove("test.txt")
        assert "test.txt" not in tracker


# =============================================================================
# Tests for domain/decisions.py
# =============================================================================


class TestDecisionMatrix:
    """Test DecisionMatrix."""

    def test_local_during_download_cancels(self) -> None:
        """Local event during download should cancel and requeue."""
        matrix = DecisionMatrix()
        action, reason = matrix.evaluate(
            new_event_source="LOCAL",
            new_event_type="LOCAL_MODIFIED",
            existing_transfer_type="DOWNLOAD",
        )
        assert action == DecisionAction.CANCEL_AND_REQUEUE
        assert "local" in reason.lower()

    def test_remote_modified_during_upload_marks_conflict(self) -> None:
        """Remote modified during upload should mark conflict."""
        matrix = DecisionMatrix()
        action, _ = matrix.evaluate(
            new_event_source="REMOTE",
            new_event_type="REMOTE_MODIFIED",
            existing_transfer_type="UPLOAD",
        )
        assert action == DecisionAction.MARK_CONFLICT

    def test_remote_deleted_during_upload_creates_copy(self) -> None:
        """Remote deleted during upload should create conflict copy."""
        matrix = DecisionMatrix()
        action, _ = matrix.evaluate(
            new_event_source="REMOTE",
            new_event_type="REMOTE_DELETED",
            existing_transfer_type="UPLOAD",
        )
        assert action == DecisionAction.CREATE_CONFLICT_COPY

    def test_remote_during_download_ignored(self) -> None:
        """Remote event during download should be ignored."""
        matrix = DecisionMatrix()
        action, _ = matrix.evaluate(
            new_event_source="REMOTE",
            new_event_type="REMOTE_MODIFIED",
            existing_transfer_type="DOWNLOAD",
        )
        assert action == DecisionAction.IGNORE

    def test_local_during_upload_ignored(self) -> None:
        """Local event during upload should be ignored."""
        matrix = DecisionMatrix()
        action, _ = matrix.evaluate(
            new_event_source="LOCAL",
            new_event_type="LOCAL_MODIFIED",
            existing_transfer_type="UPLOAD",
        )
        assert action == DecisionAction.IGNORE

    def test_custom_rules(self) -> None:
        """Test custom rules override default."""
        custom_rules = [
            DecisionRule(
                new_event_source="LOCAL",
                new_event_type=None,
                existing_transfer="DOWNLOAD",
                action=DecisionAction.IGNORE,  # Override default
                reason="Custom rule",
            ),
        ]
        matrix = DecisionMatrix(rules=custom_rules)
        action, reason = matrix.evaluate(
            new_event_source="LOCAL",
            new_event_type="LOCAL_MODIFIED",
            existing_transfer_type="DOWNLOAD",
        )
        assert action == DecisionAction.IGNORE
        assert reason == "Custom rule"


class TestDecideFunction:
    """Test decide() convenience function."""

    def test_decide_with_events(self) -> None:
        """Test decide() with real event and transfer objects."""
        event = SyncEvent(
            priority=SyncEventType.LOCAL_MODIFIED,  # Use int value from enum
            timestamp=time.time(),
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
            event_id="test-1",
            metadata={},
        )
        transfer = Transfer(
            path="test.txt",
            transfer_type=TransferType.DOWNLOAD,
        )

        action = decide(event, transfer)
        assert action == DecisionAction.CANCEL_AND_REQUEUE
