"""Tests for local sync state management."""

from pathlib import Path

import pytest

from syncagent.client.state import FileStatus, SyncState


class TestSyncStateCreation:
    """Tests for SyncState initialization."""

    def test_creates_database(self, tmp_path: Path) -> None:
        """Should create database file."""
        db_path = tmp_path / "state.db"
        state = SyncState(db_path)

        assert db_path.exists()
        state.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Should create parent directories."""
        db_path = tmp_path / "subdir" / "nested" / "state.db"
        state = SyncState(db_path)

        assert db_path.exists()
        state.close()

    def test_reopens_existing_db(self, tmp_path: Path) -> None:
        """Should reopen existing database."""
        db_path = tmp_path / "state.db"

        state1 = SyncState(db_path)
        state1.add_file("test.txt")
        state1.close()

        state2 = SyncState(db_path)
        file = state2.get_file("test.txt")
        assert file is not None
        assert file.path == "test.txt"
        state2.close()


class TestFileOperations:
    """Tests for file tracking operations."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> SyncState:
        """Create a SyncState instance."""
        s = SyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_add_file(self, state: SyncState) -> None:
        """Should add a file to tracking."""
        file = state.add_file(
            "docs/readme.txt",
            local_mtime=12345.0,
            local_size=100,
            local_hash="abc123",
        )

        assert file.path == "docs/readme.txt"
        assert file.local_mtime == 12345.0
        assert file.local_size == 100
        assert file.local_hash == "abc123"
        assert file.status == FileStatus.NEW

    def test_get_file(self, state: SyncState) -> None:
        """Should retrieve a tracked file."""
        state.add_file("test.txt", local_size=50)

        file = state.get_file("test.txt")
        assert file is not None
        assert file.path == "test.txt"
        assert file.local_size == 50

    def test_get_nonexistent_file(self, state: SyncState) -> None:
        """Should return None for nonexistent file."""
        file = state.get_file("nonexistent.txt")
        assert file is None

    def test_update_file(self, state: SyncState) -> None:
        """Should update file metadata."""
        state.add_file("test.txt")

        state.update_file(
            "test.txt",
            server_file_id=42,
            server_version=3,
            status=FileStatus.SYNCED,
        )

        file = state.get_file("test.txt")
        assert file is not None
        assert file.server_file_id == 42
        assert file.server_version == 3
        assert file.status == FileStatus.SYNCED

    def test_update_chunk_hashes(self, state: SyncState) -> None:
        """Should update chunk hashes as JSON."""
        state.add_file("test.txt")

        hashes = ["hash1", "hash2", "hash3"]
        state.update_file("test.txt", chunk_hashes=hashes)

        file = state.get_file("test.txt")
        assert file is not None
        assert file.chunk_hashes == hashes

    def test_delete_file(self, state: SyncState) -> None:
        """Should delete a tracked file."""
        state.add_file("test.txt")
        state.delete_file("test.txt")

        file = state.get_file("test.txt")
        assert file is None

    def test_list_files(self, state: SyncState) -> None:
        """Should list all tracked files."""
        state.add_file("a.txt")
        state.add_file("b.txt")
        state.add_file("c.txt")

        files = state.list_files()
        assert len(files) == 3
        paths = [f.path for f in files]
        assert "a.txt" in paths
        assert "b.txt" in paths
        assert "c.txt" in paths

    def test_list_files_by_status(self, state: SyncState) -> None:
        """Should filter files by status."""
        state.add_file("new.txt", status=FileStatus.NEW)
        state.add_file("modified.txt", status=FileStatus.MODIFIED)
        state.add_file("synced.txt", status=FileStatus.SYNCED)

        new_files = state.list_files(status=FileStatus.NEW)
        assert len(new_files) == 1
        assert new_files[0].path == "new.txt"

        modified = state.list_files(status=FileStatus.MODIFIED)
        assert len(modified) == 1
        assert modified[0].path == "modified.txt"

    def test_mark_synced(self, state: SyncState) -> None:
        """Should mark file as synced with server info."""
        state.add_file("test.txt")

        state.mark_synced("test.txt", server_file_id=10, server_version=2, chunk_hashes=["a", "b"])

        file = state.get_file("test.txt")
        assert file is not None
        assert file.status == FileStatus.SYNCED
        assert file.server_file_id == 10
        assert file.server_version == 2
        assert file.chunk_hashes == ["a", "b"]
        assert file.last_synced_at is not None

    def test_mark_modified(self, state: SyncState) -> None:
        """Should mark file as modified."""
        state.add_file("test.txt", status=FileStatus.SYNCED)
        state.mark_modified("test.txt")

        file = state.get_file("test.txt")
        assert file is not None
        assert file.status == FileStatus.MODIFIED

    def test_mark_conflict(self, state: SyncState) -> None:
        """Should mark file as having conflict."""
        state.add_file("test.txt")
        state.mark_conflict("test.txt")

        file = state.get_file("test.txt")
        assert file is not None
        assert file.status == FileStatus.CONFLICT


class TestPendingUploads:
    """Tests for pending upload queue."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> SyncState:
        """Create a SyncState instance."""
        s = SyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_add_pending_upload(self, state: SyncState) -> None:
        """Should add file to pending uploads."""
        state.add_pending_upload("test.txt")

        pending = state.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0].path == "test.txt"
        assert pending[0].attempts == 0

    def test_pending_uploads_ordered(self, state: SyncState) -> None:
        """Should return pending uploads in detection order."""
        state.add_pending_upload("first.txt")
        state.add_pending_upload("second.txt")
        state.add_pending_upload("third.txt")

        pending = state.get_pending_uploads()
        assert len(pending) == 3
        assert pending[0].path == "first.txt"
        assert pending[1].path == "second.txt"
        assert pending[2].path == "third.txt"

    def test_mark_upload_attempt(self, state: SyncState) -> None:
        """Should record upload attempts."""
        state.add_pending_upload("test.txt")

        state.mark_upload_attempt("test.txt", error="Network error")

        pending = state.get_pending_uploads()
        assert pending[0].attempts == 1
        assert pending[0].error == "Network error"
        assert pending[0].last_attempt_at is not None

    def test_remove_pending_upload(self, state: SyncState) -> None:
        """Should remove from pending uploads."""
        state.add_pending_upload("test.txt")
        state.remove_pending_upload("test.txt")

        pending = state.get_pending_uploads()
        assert len(pending) == 0

    def test_clear_pending_uploads(self, state: SyncState) -> None:
        """Should clear all pending uploads."""
        state.add_pending_upload("a.txt")
        state.add_pending_upload("b.txt")

        state.clear_pending_uploads()

        pending = state.get_pending_uploads()
        assert len(pending) == 0

    def test_add_pending_replaces(self, state: SyncState) -> None:
        """Adding same file again should reset it."""
        state.add_pending_upload("test.txt")
        state.mark_upload_attempt("test.txt", error="Error 1")

        state.add_pending_upload("test.txt")

        pending = state.get_pending_uploads()
        assert len(pending) == 1
        assert pending[0].attempts == 0


class TestSyncState:
    """Tests for sync state key-value storage."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> SyncState:
        """Create a SyncState instance."""
        s = SyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_get_set_state(self, state: SyncState) -> None:
        """Should store and retrieve state values."""
        state.set_state("my_key", "my_value")

        value = state.get_state("my_key")
        assert value == "my_value"

    def test_get_nonexistent_state(self, state: SyncState) -> None:
        """Should return None for nonexistent key."""
        value = state.get_state("nonexistent")
        assert value is None

    def test_update_state(self, state: SyncState) -> None:
        """Should update existing state."""
        state.set_state("key", "value1")
        state.set_state("key", "value2")

        value = state.get_state("key")
        assert value == "value2"

    def test_last_sync_at(self, state: SyncState) -> None:
        """Should track last sync timestamp."""
        assert state.get_last_sync_at() is None

        state.set_last_sync_at(12345.67)
        assert state.get_last_sync_at() == 12345.67

    def test_last_server_version(self, state: SyncState) -> None:
        """Should track last server version."""
        assert state.get_last_server_version() is None

        state.set_last_server_version(42)
        assert state.get_last_server_version() == 42


class TestLocalFile:
    """Tests for LocalFile dataclass."""

    def test_file_status_values(self) -> None:
        """FileStatus enum should have expected values."""
        assert FileStatus.SYNCED.value == "synced"
        assert FileStatus.MODIFIED.value == "modified"
        assert FileStatus.PENDING_UPLOAD.value == "pending_upload"
        assert FileStatus.CONFLICT.value == "conflict"
        assert FileStatus.NEW.value == "new"


class TestUploadProgress:
    """Tests for upload progress tracking (Phase 12)."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> SyncState:
        """Create a SyncState instance."""
        s = SyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_start_upload_progress(self, state: SyncState) -> None:
        """Should start tracking upload progress."""
        chunk_hashes = ["hash1", "hash2", "hash3"]
        progress = state.start_upload_progress("test.txt", chunk_hashes)

        assert progress.path == "test.txt"
        assert progress.total_chunks == 3
        assert progress.uploaded_chunks == 0
        assert progress.chunk_hashes == chunk_hashes
        assert progress.uploaded_hashes == []
        assert progress.started_at > 0
        assert progress.updated_at > 0

    def test_get_upload_progress(self, state: SyncState) -> None:
        """Should retrieve upload progress."""
        state.start_upload_progress("test.txt", ["hash1", "hash2"])

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.path == "test.txt"
        assert progress.total_chunks == 2

    def test_get_nonexistent_progress(self, state: SyncState) -> None:
        """Should return None for nonexistent progress."""
        progress = state.get_upload_progress("nonexistent.txt")
        assert progress is None

    def test_mark_chunk_uploaded(self, state: SyncState) -> None:
        """Should mark chunks as uploaded."""
        state.start_upload_progress("test.txt", ["hash1", "hash2", "hash3"])

        state.mark_chunk_uploaded("test.txt", "hash1")

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.uploaded_chunks == 1
        assert "hash1" in progress.uploaded_hashes

    def test_mark_multiple_chunks_uploaded(self, state: SyncState) -> None:
        """Should track multiple uploaded chunks."""
        state.start_upload_progress("test.txt", ["hash1", "hash2", "hash3"])

        state.mark_chunk_uploaded("test.txt", "hash1")
        state.mark_chunk_uploaded("test.txt", "hash2")

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.uploaded_chunks == 2
        assert set(progress.uploaded_hashes) == {"hash1", "hash2"}

    def test_mark_same_chunk_twice(self, state: SyncState) -> None:
        """Should not duplicate chunk in uploaded list."""
        state.start_upload_progress("test.txt", ["hash1", "hash2"])

        state.mark_chunk_uploaded("test.txt", "hash1")
        state.mark_chunk_uploaded("test.txt", "hash1")

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.uploaded_chunks == 1
        assert progress.uploaded_hashes.count("hash1") == 1

    def test_clear_upload_progress(self, state: SyncState) -> None:
        """Should clear upload progress."""
        state.start_upload_progress("test.txt", ["hash1"])
        state.clear_upload_progress("test.txt")

        progress = state.get_upload_progress("test.txt")
        assert progress is None

    def test_get_remaining_chunks(self, state: SyncState) -> None:
        """Should return chunks not yet uploaded."""
        state.start_upload_progress("test.txt", ["hash1", "hash2", "hash3"])
        state.mark_chunk_uploaded("test.txt", "hash2")

        remaining = state.get_remaining_chunks("test.txt")
        assert set(remaining) == {"hash1", "hash3"}

    def test_get_remaining_chunks_nonexistent(self, state: SyncState) -> None:
        """Should return empty list for nonexistent file."""
        remaining = state.get_remaining_chunks("nonexistent.txt")
        assert remaining == []

    def test_clear_all_upload_progress(self, state: SyncState) -> None:
        """Should clear all upload progress records."""
        state.start_upload_progress("file1.txt", ["hash1"])
        state.start_upload_progress("file2.txt", ["hash2"])

        state.clear_all_upload_progress()

        assert state.get_upload_progress("file1.txt") is None
        assert state.get_upload_progress("file2.txt") is None

    def test_upload_progress_is_complete(self, state: SyncState) -> None:
        """Should detect when upload is complete."""
        state.start_upload_progress("test.txt", ["hash1", "hash2"])

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert not progress.is_complete

        state.mark_chunk_uploaded("test.txt", "hash1")
        state.mark_chunk_uploaded("test.txt", "hash2")

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.is_complete

    def test_upload_progress_percent(self, state: SyncState) -> None:
        """Should calculate upload percentage correctly."""
        state.start_upload_progress("test.txt", ["hash1", "hash2", "hash3", "hash4"])

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.percent == 0.0

        state.mark_chunk_uploaded("test.txt", "hash1")
        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.percent == 25.0

        state.mark_chunk_uploaded("test.txt", "hash2")
        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.percent == 50.0

    def test_start_progress_replaces_existing(self, state: SyncState) -> None:
        """Starting progress for same file should replace existing."""
        state.start_upload_progress("test.txt", ["hash1", "hash2"])
        state.mark_chunk_uploaded("test.txt", "hash1")

        # Start new progress (file changed)
        state.start_upload_progress("test.txt", ["new_hash1", "new_hash2", "new_hash3"])

        progress = state.get_upload_progress("test.txt")
        assert progress is not None
        assert progress.total_chunks == 3
        assert progress.uploaded_chunks == 0
        assert progress.chunk_hashes == ["new_hash1", "new_hash2", "new_hash3"]
