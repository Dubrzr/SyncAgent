"""Tests for worker classes."""

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from syncagent.client.sync.types import (
    SyncEvent,
    SyncEventSource,
    SyncEventType,
    TransferType,
)
from syncagent.client.sync.workers import (
    BaseWorker,
    CancelledException,
    DeleteWorker,
    DownloadWorker,
    PoolState,
    UploadWorker,
    WorkerContext,
    WorkerPool,
    WorkerResult,
    WorkerState,
)


class TestWorkerState:
    """Tests for WorkerState enum."""

    def test_states_defined(self) -> None:
        """Should have all required states."""
        assert WorkerState.IDLE is not None
        assert WorkerState.RUNNING is not None
        assert WorkerState.COMPLETED is not None
        assert WorkerState.CANCELLED is not None
        assert WorkerState.FAILED is not None


class TestWorkerResult:
    """Tests for WorkerResult dataclass."""

    def test_create_success_result(self) -> None:
        """Should create a success result."""
        result = WorkerResult(success=True, result="test_value")
        assert result.success is True
        assert result.result == "test_value"
        assert result.error is None
        assert result.cancelled is False

    def test_create_failure_result(self) -> None:
        """Should create a failure result."""
        result = WorkerResult(success=False, error="test error")
        assert result.success is False
        assert result.error == "test error"

    def test_create_cancelled_result(self) -> None:
        """Should create a cancelled result."""
        result = WorkerResult(success=False, cancelled=True)
        assert result.success is False
        assert result.cancelled is True


class TestWorkerContext:
    """Tests for WorkerContext dataclass."""

    def test_create_context(self) -> None:
        """Should create a context with event."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        ctx = WorkerContext(event=event)
        assert ctx.event == event
        assert ctx.cancel_check() is False
        assert ctx.on_progress is None

    def test_context_with_cancel_check(self) -> None:
        """Should support custom cancel check."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        cancelled = False

        def check_cancel() -> bool:
            return cancelled

        ctx = WorkerContext(event=event, cancel_check=check_cancel)
        assert ctx.cancel_check() is False

        cancelled = True
        assert ctx.cancel_check() is True


class ConcreteWorker(BaseWorker):
    """Concrete worker implementation for testing."""

    def __init__(self, work_result: str = "done", raise_error: bool = False) -> None:
        super().__init__()
        self._work_result = work_result
        self._raise_error = raise_error
        self.work_called = False

    @property
    def worker_type(self) -> str:
        return "test"

    def _do_work(self, ctx: WorkerContext) -> str:
        self.work_called = True
        if self._raise_error:
            raise ValueError("Test error")
        if ctx.cancel_check():
            raise CancelledException("Cancelled")
        return self._work_result


class TestBaseWorker:
    """Tests for BaseWorker abstract class."""

    def test_initial_state(self) -> None:
        """Should start in idle state."""
        worker = ConcreteWorker()
        assert worker.state == WorkerState.IDLE
        assert worker.is_running is False
        assert worker.cancel_requested is False

    def test_execute_success(self) -> None:
        """Should execute work and complete successfully."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker(work_result="success")
        result = worker.execute(event)

        assert result is True
        assert worker.work_called is True
        assert worker.state == WorkerState.COMPLETED

    def test_execute_failure(self) -> None:
        """Should handle errors correctly."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker(raise_error=True)
        result = worker.execute(event)

        assert result is False
        assert worker.state == WorkerState.FAILED

    def test_cancel_during_execution(self) -> None:
        """Should handle cancellation."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker()

        # Pre-cancel
        def always_cancelled() -> bool:
            return True

        result = worker.execute(event, cancel_check=always_cancelled)

        assert result is False
        assert worker.state == WorkerState.CANCELLED

    def test_cancel_method(self) -> None:
        """Should request cancellation via cancel() method."""
        worker = ConcreteWorker()
        # Can't cancel if not running
        assert worker.cancel() is False

    def test_on_complete_callback(self) -> None:
        """Should call on_complete callback."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker()
        callback_results: list[WorkerResult] = []
        worker.set_on_complete(lambda r: callback_results.append(r))

        worker.execute(event)

        assert len(callback_results) == 1
        assert callback_results[0].success is True

    def test_on_error_callback(self) -> None:
        """Should call on_error callback."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker(raise_error=True)
        errors: list[str] = []
        worker.set_on_error(lambda e: errors.append(e))

        worker.execute(event)

        assert len(errors) == 1
        assert "Test error" in errors[0]

    def test_reset(self) -> None:
        """Should reset worker state."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )
        worker = ConcreteWorker()
        worker.execute(event)
        assert worker.state == WorkerState.COMPLETED

        worker.reset()
        assert worker.state == WorkerState.IDLE


class TestUploadWorker:
    """Tests for UploadWorker."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock SyncClient."""
        return MagicMock()

    @pytest.fixture
    def encryption_key(self) -> bytes:
        """Generate test encryption key."""
        from syncagent.core.crypto import derive_key, generate_salt

        return derive_key("test", generate_salt())

    def test_worker_type(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should return correct worker type."""
        worker = UploadWorker(mock_client, encryption_key, tmp_path)
        assert worker.worker_type == "upload"

    def test_upload_success(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should upload file successfully."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("test content")

        # Mock client
        mock_client.chunk_exists.return_value = False
        mock_file = MagicMock()
        mock_file.id = 1
        mock_file.version = 1
        mock_client.create_file.return_value = mock_file

        # Create event
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_CREATED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )

        worker = UploadWorker(mock_client, encryption_key, tmp_path)
        result = worker.execute(event)

        assert result is True
        mock_client.upload_chunk.assert_called()
        mock_client.create_file.assert_called_once()


class TestDownloadWorker:
    """Tests for DownloadWorker."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock SyncClient."""
        return MagicMock()

    @pytest.fixture
    def encryption_key(self) -> bytes:
        """Generate test encryption key."""
        from syncagent.core.crypto import derive_key, generate_salt

        return derive_key("test", generate_salt())

    def test_worker_type(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should return correct worker type."""
        worker = DownloadWorker(mock_client, encryption_key, tmp_path)
        assert worker.worker_type == "download"

    def test_download_success(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should download file successfully."""
        from syncagent.core.crypto import encrypt_chunk

        # Mock server file
        mock_file = MagicMock()
        mock_file.path = "test.txt"
        mock_file.size = 12
        mock_file.version = 1
        mock_client.get_file.return_value = mock_file

        # Mock chunk download
        encrypted = encrypt_chunk(b"test content", encryption_key)
        mock_client.get_file_chunks.return_value = ["hash1"]
        mock_client.download_chunk.return_value = encrypted

        # Create event
        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_CREATED,
            path="test.txt",
            source=SyncEventSource.REMOTE,
        )

        worker = DownloadWorker(mock_client, encryption_key, tmp_path)
        result = worker.execute(event)

        assert result is True
        assert (tmp_path / "test.txt").exists()
        assert (tmp_path / "test.txt").read_bytes() == b"test content"


class TestDeleteWorker:
    """Tests for DeleteWorker."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock SyncClient."""
        return MagicMock()

    def test_worker_type(self, mock_client: MagicMock, tmp_path: Path) -> None:
        """Should return correct worker type."""
        worker = DeleteWorker(mock_client, tmp_path)
        assert worker.worker_type == "delete"

    def test_delete_local_propagates_to_server(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Should propagate local deletion to server."""
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_DELETED,
            path="deleted.txt",
            source=SyncEventSource.LOCAL,
        )

        worker = DeleteWorker(mock_client, tmp_path)
        result = worker.execute(event)

        assert result is True
        mock_client.delete_file.assert_called_once_with("deleted.txt")

    def test_delete_remote_deletes_local(
        self, mock_client: MagicMock, tmp_path: Path
    ) -> None:
        """Should delete local file when remote is deleted."""
        # Create local file
        test_file = tmp_path / "to_delete.txt"
        test_file.write_text("content")

        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_DELETED,
            path="to_delete.txt",
            source=SyncEventSource.REMOTE,
        )

        worker = DeleteWorker(mock_client, tmp_path)
        result = worker.execute(event)

        assert result is True
        assert not test_file.exists()


class TestWorkerPool:
    """Tests for WorkerPool."""

    @pytest.fixture
    def mock_client(self) -> MagicMock:
        """Create a mock SyncClient."""
        return MagicMock()

    @pytest.fixture
    def encryption_key(self) -> bytes:
        """Generate test encryption key."""
        from syncagent.core.crypto import derive_key, generate_salt

        return derive_key("test", generate_salt())

    def test_initial_state(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should start stopped."""
        pool = WorkerPool(mock_client, encryption_key, tmp_path)
        assert pool.state == PoolState.STOPPED
        assert pool.active_count == 0
        assert pool.queue_size == 0

    def test_start_stop(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should start and stop cleanly."""
        pool = WorkerPool(mock_client, encryption_key, tmp_path, max_workers=2)

        pool.start()
        assert pool.state == PoolState.RUNNING

        pool.stop()
        assert pool.state == PoolState.STOPPED

    def test_submit_when_stopped(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should reject submissions when stopped."""
        pool = WorkerPool(mock_client, encryption_key, tmp_path)

        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_CREATED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )

        result = pool.submit(event, TransferType.UPLOAD)
        assert result is False

    def test_submit_and_execute(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should execute submitted tasks."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("content")

        # Mock client
        mock_client.chunk_exists.return_value = False
        mock_file = MagicMock()
        mock_file.id = 1
        mock_file.version = 1
        mock_client.create_file.return_value = mock_file

        pool = WorkerPool(mock_client, encryption_key, tmp_path, max_workers=1)
        pool.start()

        completed = threading.Event()

        def on_complete(result: WorkerResult) -> None:
            completed.set()

        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_CREATED,
            path="test.txt",
            source=SyncEventSource.LOCAL,
        )

        pool.submit(event, TransferType.UPLOAD, on_complete=on_complete)

        # Wait for completion
        assert completed.wait(timeout=5.0)
        assert pool.completed_count >= 1

        pool.stop()

    def test_cancel_task(
        self,
        mock_client: MagicMock,
        encryption_key: bytes,
        tmp_path: Path,
    ) -> None:
        """Should cancel tasks by path."""
        pool = WorkerPool(mock_client, encryption_key, tmp_path)
        pool.start()

        # No active task
        assert pool.cancel("test.txt") is False

        pool.stop()
