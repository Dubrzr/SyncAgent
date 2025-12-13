"""Tests for sync domain modules.

Tests for:
- domain/priorities.py - Event priority and ordering
- domain/transfers.py - Transfer state machine
- domain/versions.py - Version tracking
- domain/conflicts.py - Conflict detection
- domain/decisions.py - Decision matrix
"""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from syncagent.client.sync.domain import (
    ConflictContext,
    ConflictOutcome,
    DecisionAction,
    DecisionMatrix,
    DecisionRule,
    InvalidTransitionError,
    MtimeAwareComparator,
    PreDownloadConflictDetector,
    PreUploadConflictDetector,
    Priority,
    Transfer,
    TransferStatus,
    TransferTracker,
    TransferType,
    VersionChecker,
    VersionInfo,
    VersionUpdater,
    decide,
    generate_conflict_filename,
    get_priority,
    get_priority_reason,
    safe_rename,
)
from syncagent.client.sync.types import SyncEvent, SyncEventSource, SyncEventType

# =============================================================================
# Tests for domain/priorities.py
# =============================================================================


class TestPriority:
    """Test Priority enum and rules."""

    def test_priority_order(self) -> None:
        """Critical < High < Normal < Low."""
        assert Priority.CRITICAL < Priority.HIGH
        assert Priority.HIGH < Priority.NORMAL
        assert Priority.NORMAL < Priority.LOW

    def test_get_priority_delete_is_critical(self) -> None:
        """Delete events have critical priority."""
        assert get_priority("LOCAL_DELETED") == Priority.CRITICAL
        assert get_priority("REMOTE_DELETED") == Priority.CRITICAL

    def test_get_priority_local_is_high(self) -> None:
        """Local events have high priority."""
        assert get_priority("LOCAL_CREATED") == Priority.HIGH
        assert get_priority("LOCAL_MODIFIED") == Priority.HIGH

    def test_get_priority_remote_is_normal(self) -> None:
        """Remote events have normal priority."""
        assert get_priority("REMOTE_CREATED") == Priority.NORMAL
        assert get_priority("REMOTE_MODIFIED") == Priority.NORMAL

    def test_get_priority_unknown_is_normal(self) -> None:
        """Unknown events default to normal priority."""
        assert get_priority("UNKNOWN_EVENT") == Priority.NORMAL

    def test_get_priority_reason(self) -> None:
        """Priority reasons are documented."""
        reason = get_priority_reason("LOCAL_DELETED")
        assert "uploading" in reason.lower() or "deleting" in reason.lower()

        reason = get_priority_reason("UNKNOWN_EVENT")
        assert "default" in reason.lower()


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
            priority=Priority.NORMAL,
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
# Tests for domain/versions.py
# =============================================================================


class MockVersionStore:
    """Mock version store for testing."""

    def __init__(self) -> None:
        self._data: dict[str, VersionInfo] = {}

    def get_version_info(self, path: str) -> VersionInfo | None:
        return self._data.get(path)

    def set_version_info(self, path: str, info: VersionInfo) -> None:
        self._data[path] = info

    def delete_version_info(self, path: str) -> None:
        self._data.pop(path, None)


class TestVersionChecker:
    """Test VersionChecker."""

    def test_is_locally_modified_new_file(self) -> None:
        """New file is considered modified."""
        store = MockVersionStore()
        checker = VersionChecker(store)

        assert checker.is_locally_modified("new.txt", 100.0, 1024) is True

    def test_is_locally_modified_same_state(self) -> None:
        """Same mtime/size is not modified."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=1, local_mtime=100.0, local_size=1024),
        )
        checker = VersionChecker(store)

        assert checker.is_locally_modified("test.txt", 100.0, 1024) is False

    def test_is_locally_modified_mtime_changed(self) -> None:
        """Changed mtime means modified."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=1, local_mtime=100.0, local_size=1024),
        )
        checker = VersionChecker(store)

        assert checker.is_locally_modified("test.txt", 200.0, 1024) is True

    def test_is_locally_modified_size_changed(self) -> None:
        """Changed size means modified."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=1, local_mtime=100.0, local_size=1024),
        )
        checker = VersionChecker(store)

        assert checker.is_locally_modified("test.txt", 100.0, 2048) is True

    def test_get_parent_version(self) -> None:
        """Get parent version for updates."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=5, local_mtime=100.0, local_size=1024),
        )
        checker = VersionChecker(store)

        assert checker.get_parent_version("test.txt") == 5
        assert checker.get_parent_version("new.txt") is None

    def test_needs_download(self) -> None:
        """Check if download is needed."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=5, local_mtime=100.0, local_size=1024),
        )
        checker = VersionChecker(store)

        assert checker.needs_download("test.txt", 5) is False  # Same version
        assert checker.needs_download("test.txt", 6) is True  # Newer
        assert checker.needs_download("new.txt", 1) is True  # Don't have it


class TestVersionUpdater:
    """Test VersionUpdater."""

    def test_mark_synced(self) -> None:
        """Test marking file as synced."""
        store = MockVersionStore()
        updater = VersionUpdater(store)

        updater.mark_synced("test.txt", server_version=3, local_mtime=100.0, local_size=1024)

        info = store.get_version_info("test.txt")
        assert info is not None
        assert info.server_version == 3
        assert info.local_mtime == 100.0
        assert info.local_size == 1024

    def test_mark_deleted(self) -> None:
        """Test marking file as deleted."""
        store = MockVersionStore()
        store.set_version_info(
            "test.txt",
            VersionInfo(server_version=1, local_mtime=100.0, local_size=1024),
        )
        updater = VersionUpdater(store)

        updater.mark_deleted("test.txt")

        assert store.get_version_info("test.txt") is None


# =============================================================================
# Tests for domain/conflicts.py
# =============================================================================


class TestPreDownloadConflictDetector:
    """Test PreDownloadConflictDetector."""

    def test_no_conflict_file_not_exists(self) -> None:
        """No conflict if file doesn't exist."""
        detector = PreDownloadConflictDetector()
        ctx = ConflictContext(
            local_path=Path("/nonexistent/file.txt"),
            relative_path="file.txt",
            local_mtime=100.0,
            local_size=1024,
            local_hash=None,
            server_version=1,
            server_hash=None,
            expected_version=1,
        )
        assert detector.check(ctx) == ConflictOutcome.NO_CONFLICT

    def test_conflict_untracked_file(self) -> None:
        """Conflict if file exists but untracked."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            temp_path = Path(f.name)

        try:
            detector = PreDownloadConflictDetector()
            ctx = ConflictContext(
                local_path=temp_path,
                relative_path="file.txt",
                local_mtime=None,  # Untracked
                local_size=None,
                local_hash=None,
                server_version=1,
                server_hash=None,
                expected_version=1,
            )
            assert detector.check(ctx) == ConflictOutcome.RESOLVED
        finally:
            temp_path.unlink()

    def test_conflict_modified_file(self) -> None:
        """Conflict if file was modified since tracking."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            temp_path = Path(f.name)

        try:
            stat = temp_path.stat()
            detector = PreDownloadConflictDetector()
            ctx = ConflictContext(
                local_path=temp_path,
                relative_path="file.txt",
                local_mtime=stat.st_mtime - 10,  # Tracked with older mtime
                local_size=stat.st_size,
                local_hash=None,
                server_version=1,
                server_hash=None,
                expected_version=1,
            )
            assert detector.check(ctx) == ConflictOutcome.RESOLVED
        finally:
            temp_path.unlink()

    def test_no_conflict_same_state(self) -> None:
        """No conflict if file matches tracked state."""
        with tempfile.NamedTemporaryFile(delete=False) as f:
            f.write(b"test content")
            temp_path = Path(f.name)

        try:
            stat = temp_path.stat()
            detector = PreDownloadConflictDetector()
            ctx = ConflictContext(
                local_path=temp_path,
                relative_path="file.txt",
                local_mtime=stat.st_mtime,
                local_size=stat.st_size,
                local_hash=None,
                server_version=1,
                server_hash=None,
                expected_version=1,
            )
            assert detector.check(ctx) == ConflictOutcome.NO_CONFLICT
        finally:
            temp_path.unlink()


class TestPreUploadConflictDetector:
    """Test PreUploadConflictDetector."""

    def test_no_conflict_new_file(self) -> None:
        """No conflict for new file (no expected version)."""
        detector = PreUploadConflictDetector()
        ctx = ConflictContext(
            local_path=Path("test.txt"),
            relative_path="test.txt",
            local_mtime=100.0,
            local_size=1024,
            local_hash=None,
            server_version=None,
            server_hash=None,
            expected_version=None,  # New file
        )
        assert detector.check(ctx) == ConflictOutcome.NO_CONFLICT

    def test_no_conflict_same_version(self) -> None:
        """No conflict if server version matches expected."""
        detector = PreUploadConflictDetector()
        ctx = ConflictContext(
            local_path=Path("test.txt"),
            relative_path="test.txt",
            local_mtime=100.0,
            local_size=1024,
            local_hash=None,
            server_version=5,
            server_hash=None,
            expected_version=5,
        )
        assert detector.check(ctx) == ConflictOutcome.NO_CONFLICT

    def test_conflict_version_mismatch(self) -> None:
        """Conflict if server version differs from expected."""
        detector = PreUploadConflictDetector()
        ctx = ConflictContext(
            local_path=Path("test.txt"),
            relative_path="test.txt",
            local_mtime=100.0,
            local_size=1024,
            local_hash=None,
            server_version=6,  # Server was updated
            server_hash=None,
            expected_version=5,
        )
        assert detector.check(ctx) == ConflictOutcome.RESOLVED

    def test_conflict_server_deleted(self) -> None:
        """Conflict if file was deleted on server."""
        detector = PreUploadConflictDetector()
        ctx = ConflictContext(
            local_path=Path("test.txt"),
            relative_path="test.txt",
            local_mtime=100.0,
            local_size=1024,
            local_hash=None,
            server_version=None,  # Deleted
            server_hash=None,
            expected_version=5,
        )
        assert detector.check(ctx) == ConflictOutcome.RESOLVED


class TestConflictFilename:
    """Test conflict filename generation."""

    def test_generate_conflict_filename(self) -> None:
        """Test filename format."""
        path = Path("/tmp/document.txt")
        conflict_path = generate_conflict_filename(path, machine_name="laptop")

        assert conflict_path.parent == path.parent
        assert conflict_path.name.startswith("document.conflict-")
        assert "-laptop" in conflict_path.name
        assert conflict_path.suffix == ".txt"

    def test_generate_conflict_filename_no_extension(self) -> None:
        """Test with file without extension."""
        path = Path("/tmp/Makefile")
        conflict_path = generate_conflict_filename(path, machine_name="laptop")

        assert conflict_path.name.startswith("Makefile.conflict-")
        assert "-laptop" in conflict_path.name


class TestSafeRename:
    """Test safe_rename function."""

    def test_safe_rename_success(self) -> None:
        """Successful rename without modification."""
        with tempfile.TemporaryDirectory() as tmpdir:
            src = Path(tmpdir) / "source.txt"
            dst = Path(tmpdir) / "dest.txt"
            src.write_text("content")

            safe_rename(src, dst)

            assert not src.exists()
            assert dst.exists()
            assert dst.read_text() == "content"


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
            priority=Priority.HIGH,
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
