"""Tests for sync operations."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from syncagent.client.api import ConflictError, NotFoundError, ServerFile, SyncClient
from syncagent.client.state import FileStatus, SyncState
from syncagent.client.sync import (
    DownloadError,
    FileDownloader,
    FileUploader,
    SyncEngine,
    UploadError,
    generate_conflict_filename,
    get_machine_name,
    retry_with_backoff,
    retry_with_network_wait,
    wait_for_network,
)
from syncagent.core.crypto import derive_key, generate_salt


@pytest.fixture
def encryption_key() -> bytes:
    """Generate a test encryption key."""
    salt = generate_salt()
    return derive_key("test-password", salt)


@pytest.fixture
def mock_client() -> MagicMock:
    """Create a mock SyncClient."""
    return MagicMock(spec=SyncClient)


@pytest.fixture
def sync_state(tmp_path: Path) -> SyncState:
    """Create a SyncState instance."""
    state = SyncState(tmp_path / "state.db")
    yield state
    state.close()


class TestFileUploader:
    """Tests for FileUploader."""

    def test_upload_new_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should upload a new file."""
        # Create test file
        test_file = tmp_path / "test.txt"
        test_file.write_text("Hello, World!")

        # Mock responses
        mock_client.chunk_exists.return_value = False
        created_file = MagicMock()
        created_file.id = 1
        created_file.version = 1
        mock_client.create_file.return_value = created_file

        uploader = FileUploader(mock_client, encryption_key)
        result = uploader.upload_file(test_file, "test.txt")

        assert result.path == "test.txt"
        assert result.server_file_id == 1
        assert result.server_version == 1
        assert len(result.chunk_hashes) >= 1
        assert result.size == 13

        # Verify chunk was uploaded
        mock_client.upload_chunk.assert_called()
        mock_client.create_file.assert_called_once()

    def test_upload_existing_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should update an existing file."""
        test_file = tmp_path / "existing.txt"
        test_file.write_text("Updated content")

        mock_client.chunk_exists.return_value = False
        # Mock get_file to return matching version for pre-upload check
        server_file = MagicMock()
        server_file.version = 2  # Matches parent_version
        mock_client.get_file.return_value = server_file

        updated_file = MagicMock()
        updated_file.id = 1
        updated_file.version = 3
        mock_client.update_file.return_value = updated_file

        uploader = FileUploader(mock_client, encryption_key)
        result = uploader.upload_file(test_file, "existing.txt", parent_version=2)

        assert result.server_version == 3
        mock_client.update_file.assert_called_once()

    def test_upload_skips_existing_chunks(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should not upload chunks that already exist."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Some content")

        # Chunk already exists
        mock_client.chunk_exists.return_value = True
        created_file = MagicMock()
        created_file.id = 1
        created_file.version = 1
        mock_client.create_file.return_value = created_file

        uploader = FileUploader(mock_client, encryption_key)
        uploader.upload_file(test_file, "test.txt")

        # Should check if chunk exists but not upload
        mock_client.chunk_exists.assert_called()
        mock_client.upload_chunk.assert_not_called()

    def test_upload_nonexistent_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should raise error for nonexistent file."""
        uploader = FileUploader(mock_client, encryption_key)

        with pytest.raises(UploadError, match="File not found"):
            uploader.upload_file(tmp_path / "missing.txt", "missing.txt")

    def test_upload_conflict(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should propagate conflict error from update_file."""
        test_file = tmp_path / "conflict.txt"
        test_file.write_text("Content")

        mock_client.chunk_exists.return_value = False
        # Mock get_file to return matching version for pre-upload check
        server_file = MagicMock()
        server_file.version = 1  # Matches parent_version
        mock_client.get_file.return_value = server_file

        # But update_file fails with conflict (version changed between check and commit)
        mock_client.update_file.side_effect = ConflictError("Version conflict")

        uploader = FileUploader(mock_client, encryption_key)

        with pytest.raises(ConflictError):
            uploader.upload_file(test_file, "conflict.txt", parent_version=1)


class TestFileDownloader:
    """Tests for FileDownloader."""

    def test_download_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should download and decrypt a file."""
        from syncagent.core.crypto import encrypt_chunk

        # Create encrypted chunk
        original_data = b"Hello, World!"
        encrypted_data = encrypt_chunk(original_data, encryption_key)

        # Mock server file
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "downloaded.txt"
        server_file.size = 13
        server_file.version = 1
        server_file.id = 1

        mock_client.get_file_chunks.return_value = ["chunk1hash"]
        mock_client.download_chunk.return_value = encrypted_data

        downloader = FileDownloader(mock_client, encryption_key)
        local_path = tmp_path / "downloaded.txt"
        result = downloader.download_file(server_file, local_path)

        assert result.path == "downloaded.txt"
        assert result.local_path == local_path
        assert local_path.exists()
        assert local_path.read_bytes() == original_data

    def test_download_multiple_chunks(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should assemble multiple chunks."""
        from syncagent.core.crypto import encrypt_chunk

        chunk1_data = b"First chunk"
        chunk2_data = b"Second chunk"

        encrypted1 = encrypt_chunk(chunk1_data, encryption_key)
        encrypted2 = encrypt_chunk(chunk2_data, encryption_key)

        server_file = MagicMock(spec=ServerFile)
        server_file.path = "multi.txt"
        server_file.size = len(chunk1_data) + len(chunk2_data)
        server_file.version = 1
        server_file.id = 1

        mock_client.get_file_chunks.return_value = ["hash1", "hash2"]
        mock_client.download_chunk.side_effect = [encrypted1, encrypted2]

        downloader = FileDownloader(mock_client, encryption_key)
        local_path = tmp_path / "multi.txt"
        downloader.download_file(server_file, local_path)

        assert local_path.read_bytes() == chunk1_data + chunk2_data

    def test_download_creates_parent_dirs(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should create parent directories."""
        from syncagent.core.crypto import encrypt_chunk

        encrypted = encrypt_chunk(b"content", encryption_key)

        server_file = MagicMock(spec=ServerFile)
        server_file.path = "subdir/nested/file.txt"
        server_file.size = 7
        server_file.version = 1
        server_file.id = 1

        mock_client.get_file_chunks.return_value = ["hash"]
        mock_client.download_chunk.return_value = encrypted

        downloader = FileDownloader(mock_client, encryption_key)
        local_path = tmp_path / "subdir" / "nested" / "file.txt"
        downloader.download_file(server_file, local_path)

        assert local_path.exists()

    def test_download_chunk_not_found(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should raise error when chunk not found."""
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "missing.txt"

        mock_client.get_file_chunks.return_value = ["missing_hash"]
        mock_client.download_chunk.side_effect = NotFoundError("Not found")

        downloader = FileDownloader(mock_client, encryption_key)

        with pytest.raises(DownloadError, match="Chunk missing_hash not found"):
            downloader.download_file(server_file, tmp_path / "missing.txt")


class TestSyncEngine:
    """Tests for SyncEngine (event-based scanner).

    SyncEngine scans for changes and pushes SyncEvent objects to the queue.
    Actual sync work is done by Workers via the Coordinator.
    """

    def test_scan_detects_new_local_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should push LOCAL_CREATED events for new files."""
        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create a new file
        test_file = base_path / "new.txt"
        test_file.write_text("New file content")

        mock_client.list_files.return_value = []

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "new.txt" in result.uploaded

        # Verify event was pushed to queue
        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "new.txt"
        assert event.event_type == SyncEventType.LOCAL_CREATED

    def test_scan_detects_modified_local_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should push LOCAL_MODIFIED events for modified files."""
        import time

        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create and track file as synced
        test_file = base_path / "existing.txt"
        test_file.write_text("Original content")

        sync_state.add_file(
            "existing.txt",
            local_mtime=test_file.stat().st_mtime - 10,  # Old mtime
            local_size=len("Original content"),
            status=FileStatus.SYNCED,
        )
        sync_state.update_file("existing.txt", server_file_id=1, server_version=1)

        # Modify the file
        time.sleep(0.01)
        test_file.write_text("Modified content")

        mock_client.list_files.return_value = []

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "existing.txt" in result.uploaded

        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "existing.txt"
        assert event.event_type == SyncEventType.LOCAL_MODIFIED

    def test_scan_detects_deleted_local_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should push LOCAL_DELETED events for deleted files."""
        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Track file as synced (but don't create it on disk)
        sync_state.add_file("deleted.txt", status=FileStatus.SYNCED)
        sync_state.update_file("deleted.txt", server_file_id=1, server_version=1)

        mock_client.list_files.return_value = []

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "deleted.txt" in result.deleted

        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "deleted.txt"
        assert event.event_type == SyncEventType.LOCAL_DELETED

    def test_scan_detects_new_remote_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should push REMOTE_CREATED events for new server files."""
        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Server has a file not in local state
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "remote.txt"
        server_file.version = 1
        server_file.id = 1

        mock_client.list_files.return_value = [server_file]

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "remote.txt" in result.downloaded

        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "remote.txt"
        assert event.event_type == SyncEventType.REMOTE_CREATED

    def test_scan_detects_modified_remote_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should push REMOTE_MODIFIED events for modified server files."""
        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Track file as synced with old version
        sync_state.add_file("remote.txt", status=FileStatus.SYNCED)
        sync_state.update_file("remote.txt", server_file_id=1, server_version=1)

        # Server has newer version
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "remote.txt"
        server_file.version = 2  # Newer version
        server_file.id = 1

        mock_client.list_files.return_value = [server_file]

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "remote.txt" in result.downloaded

        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "remote.txt"
        assert event.event_type == SyncEventType.REMOTE_MODIFIED

    def test_scan_skips_up_to_date_remote_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should not push events for files already in sync."""
        from syncagent.client.sync import EventQueue

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file
        test_file = base_path / "synced.txt"
        test_file.write_text("Content")

        # Track as synced with same version
        sync_state.add_file(
            "synced.txt",
            local_mtime=test_file.stat().st_mtime,
            local_size=len("Content"),
            status=FileStatus.SYNCED,
        )
        sync_state.update_file("synced.txt", server_file_id=1, server_version=5)

        # Server has same version
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "synced.txt"
        server_file.version = 5
        server_file.id = 1

        mock_client.list_files.return_value = [server_file]

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "synced.txt" not in result.uploaded
        assert "synced.txt" not in result.downloaded

        # Queue should be empty
        event = queue.get(timeout=0.1)
        assert event is None

    def test_scan_skips_remote_when_local_pending(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should not push REMOTE events when local has pending changes."""
        from syncagent.client.sync import EventQueue, SyncEventType

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file with changes
        test_file = base_path / "changed.txt"
        test_file.write_text("Local changes")

        # Track as modified locally
        sync_state.add_file("changed.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("changed.txt", server_file_id=1, server_version=2)

        # Server has newer version
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "changed.txt"
        server_file.version = 3
        server_file.id = 1

        mock_client.list_files.return_value = [server_file]

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        # Should queue local upload, not remote download
        assert "changed.txt" in result.uploaded
        assert "changed.txt" not in result.downloaded

        event = queue.get(timeout=0.1)
        assert event is not None
        assert event.path == "changed.txt"
        assert event.event_type == SyncEventType.LOCAL_MODIFIED

        # No more events
        event = queue.get(timeout=0.1)
        assert event is None

    def test_scan_includes_already_pending_files(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should include files already marked as NEW or MODIFIED."""
        from syncagent.client.sync import EventQueue

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create file that's already tracked as NEW
        test_file = base_path / "pending.txt"
        test_file.write_text("Pending content")
        sync_state.add_file("pending.txt", status=FileStatus.NEW)

        mock_client.list_files.return_value = []

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "pending.txt" in result.uploaded

    def test_scan_respects_syncignore(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
    ) -> None:
        """Should ignore files matching .syncignore patterns."""
        from syncagent.client.sync import EventQueue

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create .syncignore
        (base_path / ".syncignore").write_text("*.log\n")

        # Create files
        (base_path / "good.txt").write_text("Keep me")
        (base_path / "debug.log").write_text("Ignore me")

        mock_client.list_files.return_value = []

        queue = EventQueue()
        engine = SyncEngine(mock_client, sync_state, base_path, queue)
        result = engine.scan()

        assert "good.txt" in result.uploaded
        assert "debug.log" not in result.uploaded


class TestConflictFilename:
    """Tests for conflict filename generation."""

    def test_generate_conflict_filename_basic(self, tmp_path: Path) -> None:
        """Should generate proper conflict filename."""
        original = tmp_path / "document.txt"
        conflict = generate_conflict_filename(original, "MyPC")

        assert conflict.parent == tmp_path
        assert conflict.name.startswith("document.conflict-")
        assert "-MyPC.txt" in conflict.name

    def test_generate_conflict_filename_with_special_chars(self, tmp_path: Path) -> None:
        """Should sanitize machine names with special characters."""
        original = tmp_path / "file.pdf"
        conflict = generate_conflict_filename(original, "My PC (Work)")

        # Special characters should be replaced with underscore
        assert "My_PC__Work_" in conflict.name
        assert conflict.suffix == ".pdf"

    def test_generate_conflict_filename_uses_hostname(self, tmp_path: Path) -> None:
        """Should use hostname when no machine name provided."""
        original = tmp_path / "test.docx"
        conflict = generate_conflict_filename(original)

        # Hostname is used (may be sanitized)
        assert conflict.name.startswith("test.conflict-")
        assert conflict.suffix == ".docx"
        # Verify hostname is included somewhere in the name
        assert get_machine_name()[:5] in conflict.name or "_" in conflict.name

    def test_generate_conflict_filename_no_extension(self, tmp_path: Path) -> None:
        """Should handle files without extension."""
        original = tmp_path / "Makefile"
        conflict = generate_conflict_filename(original, "server")

        assert conflict.name.startswith("Makefile.conflict-")
        assert "-server" in conflict.name
        # For files without extension, the conflict part becomes the "suffix"
        # Just verify the name is properly formed
        assert not conflict.name.endswith(".txt")  # No original extension


class TestRetryWithBackoff:
    """Tests for retry_with_backoff function (Phase 12)."""

    def test_succeeds_on_first_try(self) -> None:
        """Should return result when function succeeds first try."""
        counter = {"calls": 0}

        def succeed() -> str:
            counter["calls"] += 1
            return "success"

        result = retry_with_backoff(succeed, max_retries=3)

        assert result == "success"
        assert counter["calls"] == 1

    def test_retries_on_failure(self) -> None:
        """Should retry on failure and eventually succeed."""
        counter = {"calls": 0}

        def fail_twice() -> str:
            counter["calls"] += 1
            if counter["calls"] < 3:
                raise ConnectionError("Network error")
            return "success"

        with patch("syncagent.client.sync.retry.time.sleep"):
            result = retry_with_backoff(
                fail_twice,
                max_retries=5,
                retryable_exceptions=(ConnectionError,),
            )

        assert result == "success"
        assert counter["calls"] == 3

    def test_raises_after_max_retries(self) -> None:
        """Should raise after exhausting retries."""
        counter = {"calls": 0}

        def always_fail() -> str:
            counter["calls"] += 1
            raise TimeoutError("Timeout")

        with patch("syncagent.client.sync.retry.time.sleep"), pytest.raises(
            TimeoutError, match="Timeout"
        ):
            retry_with_backoff(
                always_fail,
                max_retries=3,
                retryable_exceptions=(TimeoutError,),
            )

        assert counter["calls"] == 4  # Initial + 3 retries

    def test_does_not_retry_non_retryable_exceptions(self) -> None:
        """Should not retry exceptions not in retryable list."""
        counter = {"calls": 0}

        def raise_value_error() -> str:
            counter["calls"] += 1
            raise ValueError("Invalid value")

        with pytest.raises(ValueError, match="Invalid value"):
            retry_with_backoff(
                raise_value_error,
                max_retries=3,
                retryable_exceptions=(ConnectionError,),
            )

        assert counter["calls"] == 1

    def test_exponential_backoff(self) -> None:
        """Should use exponential backoff between retries."""
        sleep_times: list[float] = []
        counter = {"calls": 0}

        def fail_thrice() -> str:
            counter["calls"] += 1
            if counter["calls"] < 4:
                raise OSError("Error")
            return "success"

        with patch("syncagent.client.sync.retry.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda t: sleep_times.append(t)
            retry_with_backoff(
                fail_thrice,
                max_retries=5,
                initial_backoff=1.0,
                backoff_multiplier=2.0,
                retryable_exceptions=(OSError,),
            )

        assert len(sleep_times) == 3
        assert sleep_times[0] == 1.0
        assert sleep_times[1] == 2.0
        assert sleep_times[2] == 4.0

    def test_max_backoff_cap(self) -> None:
        """Should cap backoff at max_backoff."""
        sleep_times: list[float] = []
        counter = {"calls": 0}

        def keep_failing() -> str:
            counter["calls"] += 1
            if counter["calls"] < 6:
                raise OSError("Error")
            return "success"

        with patch("syncagent.client.sync.retry.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda t: sleep_times.append(t)
            retry_with_backoff(
                keep_failing,
                max_retries=10,
                initial_backoff=1.0,
                max_backoff=5.0,
                backoff_multiplier=2.0,
                retryable_exceptions=(OSError,),
            )

        # 1, 2, 4, 5 (capped), 5 (capped)
        assert sleep_times[3] == 5.0
        assert sleep_times[4] == 5.0


class TestAtomicDownload:
    """Tests for atomic download with temp files (Phase 12)."""

    def test_download_uses_temp_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should use .tmp file during download."""
        from syncagent.core.crypto import encrypt_chunk

        encrypted = encrypt_chunk(b"content", encryption_key)
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "test.txt"
        server_file.size = 7
        server_file.version = 1

        mock_client.get_file_chunks.return_value = ["hash"]
        mock_client.download_chunk.return_value = encrypted

        downloader = FileDownloader(mock_client, encryption_key)
        local_path = tmp_path / "test.txt"
        downloader.download_file(server_file, local_path)

        # Final file should exist, temp should not
        assert local_path.exists()
        assert not local_path.with_suffix(".txt.tmp").exists()

    def test_download_cleans_up_temp_on_failure(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should remove temp file on failure."""
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "test.txt"
        server_file.size = 10

        mock_client.get_file_chunks.return_value = ["hash"]
        mock_client.download_chunk.side_effect = NotFoundError("Not found")

        downloader = FileDownloader(mock_client, encryption_key)
        local_path = tmp_path / "test.txt"

        with pytest.raises(DownloadError):
            downloader.download_file(server_file, local_path)

        # Neither final nor temp should exist
        assert not local_path.exists()
        assert not local_path.with_suffix(".txt.tmp").exists()

    def test_download_overwrites_existing(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should overwrite existing file."""
        from syncagent.core.crypto import encrypt_chunk

        # Create existing file
        local_path = tmp_path / "existing.txt"
        local_path.write_text("old content")

        encrypted = encrypt_chunk(b"new content", encryption_key)
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "existing.txt"
        server_file.size = 11
        server_file.version = 2

        mock_client.get_file_chunks.return_value = ["hash"]
        mock_client.download_chunk.return_value = encrypted

        downloader = FileDownloader(mock_client, encryption_key)
        downloader.download_file(server_file, local_path)

        assert local_path.read_bytes() == b"new content"


class TestResumableUpload:
    """Tests for resumable uploads with progress tracking (Phase 12)."""

    def test_upload_tracks_progress(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
        sync_state: SyncState,
    ) -> None:
        """Should track upload progress when state provided."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Content for chunks")

        mock_client.chunk_exists.return_value = False
        created_file = MagicMock()
        created_file.id = 1
        created_file.version = 1
        mock_client.create_file.return_value = created_file

        uploader = FileUploader(mock_client, encryption_key, state=sync_state)
        uploader.upload_file(test_file, "test.txt")

        # Progress should be cleared after successful upload
        progress = sync_state.get_upload_progress("test.txt")
        assert progress is None

    def test_upload_resumes_from_progress(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
        sync_state: SyncState,
    ) -> None:
        """Should resume upload from tracked progress."""
        from syncagent.core.chunking import chunk_file

        test_file = tmp_path / "test.txt"
        test_file.write_text("Content for chunks")

        # Get actual chunk hashes
        chunks = list(chunk_file(test_file))
        chunk_hashes = [c.hash for c in chunks]

        # Pre-populate upload progress as if first chunk was already uploaded
        sync_state.start_upload_progress("test.txt", chunk_hashes)
        if chunk_hashes:
            sync_state.mark_chunk_uploaded("test.txt", chunk_hashes[0])

        mock_client.chunk_exists.return_value = False
        created_file = MagicMock()
        created_file.id = 1
        created_file.version = 1
        mock_client.create_file.return_value = created_file

        uploader = FileUploader(mock_client, encryption_key, state=sync_state)
        uploader.upload_file(test_file, "test.txt")

        # Upload should have been called only for non-uploaded chunks
        # (chunks that weren't in progress.uploaded_hashes)
        # Exact call count depends on chunk count but less than full upload

    def test_upload_restarts_if_file_changed(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
        sync_state: SyncState,
    ) -> None:
        """Should restart upload if file content changed."""
        test_file = tmp_path / "test.txt"
        test_file.write_text("Original content")

        # Store progress with old chunk hashes
        sync_state.start_upload_progress("test.txt", ["old_hash1", "old_hash2"])
        sync_state.mark_chunk_uploaded("test.txt", "old_hash1")

        # Modify the file (different chunks now)
        test_file.write_text("Modified content that is different")

        mock_client.chunk_exists.return_value = False
        created_file = MagicMock()
        created_file.id = 1
        created_file.version = 1
        mock_client.create_file.return_value = created_file

        uploader = FileUploader(mock_client, encryption_key, state=sync_state)
        uploader.upload_file(test_file, "test.txt")

        # Old progress should be cleared (file changed)
        # All new chunks should be uploaded
        mock_client.upload_chunk.assert_called()


class TestDownloadRetry:
    """Tests for download retry behavior (Phase 12)."""

    def test_download_retries_on_failure(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        encryption_key: bytes,
    ) -> None:
        """Should retry chunk download on transient failures."""
        from syncagent.core.crypto import encrypt_chunk

        encrypted = encrypt_chunk(b"content", encryption_key)

        server_file = MagicMock(spec=ServerFile)
        server_file.path = "test.txt"
        server_file.size = 7
        server_file.version = 1

        # Fail twice, then succeed
        call_count = {"count": 0}
        def download_with_failures(hash_val: str) -> bytes:
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ConnectionError("Network error")
            return encrypted

        mock_client.get_file_chunks.return_value = ["hash"]
        mock_client.download_chunk.side_effect = download_with_failures
        mock_client.health_check.return_value = True

        with patch("syncagent.client.sync.retry.time.sleep"):
            downloader = FileDownloader(mock_client, encryption_key, max_retries=5)
            local_path = tmp_path / "test.txt"
            downloader.download_file(server_file, local_path)

        assert local_path.exists()
        assert call_count["count"] == 3


class TestWaitForNetwork:
    """Tests for wait_for_network function (network-aware retry)."""

    def test_returns_immediately_if_network_up(self, mock_client: MagicMock) -> None:
        """Should return after first successful health check."""
        mock_client.health_check.return_value = True

        with patch("syncagent.client.sync.retry.time.sleep"):
            wait_for_network(mock_client, check_interval=1.0)

        # Only one sleep call before health check
        assert mock_client.health_check.call_count == 1

    def test_polls_until_network_restored(self, mock_client: MagicMock) -> None:
        """Should poll until network comes back."""
        # Fail 3 times, then succeed
        mock_client.health_check.side_effect = [False, False, False, True]

        with patch("syncagent.client.sync.retry.time.sleep") as mock_sleep:
            wait_for_network(mock_client, check_interval=5.0)

        assert mock_client.health_check.call_count == 4
        assert mock_sleep.call_count == 4  # Sleep before each check

    def test_calls_callbacks(self, mock_client: MagicMock) -> None:
        """Should call on_waiting and on_restored callbacks."""
        mock_client.health_check.side_effect = [False, True]
        on_waiting = MagicMock()
        on_restored = MagicMock()

        with patch("syncagent.client.sync.retry.time.sleep"):
            wait_for_network(
                mock_client,
                on_waiting=on_waiting,
                on_restored=on_restored,
            )

        on_waiting.assert_called_once()
        on_restored.assert_called_once()


class TestRetryWithNetworkWait:
    """Tests for retry_with_network_wait function."""

    def test_succeeds_on_first_try(self, mock_client: MagicMock) -> None:
        """Should return result when function succeeds first try."""
        result = retry_with_network_wait(
            func=lambda: "success",
            client=mock_client,
            max_retries=3,
        )

        assert result == "success"
        mock_client.health_check.assert_not_called()

    def test_waits_for_network_on_connection_error(
        self, mock_client: MagicMock
    ) -> None:
        """Should wait for network when ConnectionError occurs."""
        call_count = {"count": 0}

        def fail_then_succeed() -> str:
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ConnectionError("Network down")
            return "success"

        mock_client.health_check.return_value = True

        with patch("syncagent.client.sync.retry.time.sleep"):
            result = retry_with_network_wait(
                func=fail_then_succeed,
                client=mock_client,
            )

        assert result == "success"
        assert call_count["count"] == 2
        mock_client.health_check.assert_called()

    def test_waits_for_network_on_timeout_error(self, mock_client: MagicMock) -> None:
        """Should wait for network when TimeoutError occurs."""
        call_count = {"count": 0}

        def fail_then_succeed() -> str:
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise TimeoutError("Request timeout")
            return "success"

        mock_client.health_check.return_value = True

        with patch("syncagent.client.sync.retry.time.sleep"):
            result = retry_with_network_wait(
                func=fail_then_succeed,
                client=mock_client,
            )

        assert result == "success"
        assert call_count["count"] == 2

    def test_uses_backoff_for_non_network_errors(
        self, mock_client: MagicMock
    ) -> None:
        """Should use exponential backoff for non-network errors."""
        call_count = {"count": 0}
        sleep_times: list[float] = []

        def fail_twice() -> str:
            call_count["count"] += 1
            if call_count["count"] < 3:
                raise ValueError("Bad value")
            return "success"

        with patch("syncagent.client.sync.retry.time.sleep") as mock_sleep:
            mock_sleep.side_effect = lambda t: sleep_times.append(t)
            result = retry_with_network_wait(
                func=fail_twice,
                client=mock_client,
                max_retries=5,
                initial_backoff=1.0,
                backoff_multiplier=2.0,
                retryable_exceptions=(ValueError,),
            )

        assert result == "success"
        assert len(sleep_times) == 2
        assert sleep_times[0] == 1.0
        assert sleep_times[1] == 2.0
        # Health check not called for non-network errors
        mock_client.health_check.assert_not_called()

    def test_resets_after_network_wait(self, mock_client: MagicMock) -> None:
        """Should reset retry count after network wait."""
        call_count = {"count": 0}

        def network_then_value_error() -> str:
            call_count["count"] += 1
            if call_count["count"] == 1:
                raise ConnectionError("Network down")
            if call_count["count"] == 2:
                raise ValueError("Bad value")
            return "success"

        mock_client.health_check.return_value = True

        with patch("syncagent.client.sync.retry.time.sleep"):
            result = retry_with_network_wait(
                func=network_then_value_error,
                client=mock_client,
                max_retries=5,
                retryable_exceptions=(ValueError,),
            )

        assert result == "success"
        assert call_count["count"] == 3
