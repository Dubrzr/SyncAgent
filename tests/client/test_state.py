"""Tests for local sync state management.

The new simplified state:
- Only tracks synced files (no status column)
- Status is derived from disk state at runtime
- No pending_uploads or upload_progress tables
"""

import time
from pathlib import Path

import pytest

from syncagent.client.state import FileStatus, LocalSyncState, SyncedFile, derive_status


class TestSyncStateCreation:
    """Tests for SyncState initialization."""

    def test_creates_database(self, tmp_path: Path) -> None:
        """Should create database file."""
        db_path = tmp_path / "state.db"
        state = LocalSyncState(db_path)

        assert db_path.exists()
        state.close()

    def test_creates_parent_dirs(self, tmp_path: Path) -> None:
        """Should create parent directories."""
        db_path = tmp_path / "subdir" / "nested" / "state.db"
        state = LocalSyncState(db_path)

        assert db_path.exists()
        state.close()

    def test_reopens_existing_db(self, tmp_path: Path) -> None:
        """Should reopen existing database with data preserved."""
        db_path = tmp_path / "state.db"

        state1 = LocalSyncState(db_path)
        state1.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state1.close()

        state2 = LocalSyncState(db_path)
        file = state2.get_file("test.txt")
        assert file is not None
        assert file.path == "test.txt"
        state2.close()


class TestSyncedFileOperations:
    """Tests for synced file operations."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> LocalSyncState:
        """Create a SyncState instance."""
        s = LocalSyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_mark_synced_creates_record(self, state: LocalSyncState) -> None:
        """mark_synced should create a new synced file record."""
        state.mark_synced(
            "docs/readme.txt",
            server_file_id=10,
            server_version=5,
            chunk_hashes=["hash1", "hash2"],
            local_mtime=12345.0,
            local_size=100,
        )

        file = state.get_file("docs/readme.txt")
        assert file is not None
        assert file.path == "docs/readme.txt"
        assert file.local_mtime == 12345.0
        assert file.local_size == 100
        assert file.server_version == 5
        assert file.chunk_hashes == ["hash1", "hash2"]
        assert file.synced_at > 0

    def test_mark_synced_updates_existing(self, state: LocalSyncState) -> None:
        """mark_synced should update existing record."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=["a"], local_mtime=100.0, local_size=50)
        state.mark_synced("test.txt", server_file_id=1, server_version=2,
                          chunk_hashes=["b", "c"], local_mtime=200.0, local_size=100)

        file = state.get_file("test.txt")
        assert file is not None
        assert file.server_version == 2
        assert file.chunk_hashes == ["b", "c"]
        assert file.local_mtime == 200.0
        assert file.local_size == 100

    def test_get_nonexistent_file(self, state: LocalSyncState) -> None:
        """Should return None for nonexistent file."""
        file = state.get_file("nonexistent.txt")
        assert file is None

    def test_update_file(self, state: LocalSyncState) -> None:
        """Should update file metadata."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)

        state.update_file("test.txt", server_version=3, local_mtime=200.0)

        file = state.get_file("test.txt")
        assert file is not None
        assert file.server_version == 3
        assert file.local_mtime == 200.0

    def test_update_chunk_hashes(self, state: LocalSyncState) -> None:
        """Should update chunk hashes as JSON."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)

        hashes = ["hash1", "hash2", "hash3"]
        state.update_file("test.txt", chunk_hashes=hashes)

        file = state.get_file("test.txt")
        assert file is not None
        assert file.chunk_hashes == hashes

    def test_remove_file(self, state: LocalSyncState) -> None:
        """Should delete a tracked file."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state.remove_file("test.txt")

        file = state.get_file("test.txt")
        assert file is None

    def test_delete_file_alias(self, state: LocalSyncState) -> None:
        """delete_file should be an alias for remove_file."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state.delete_file("test.txt")

        file = state.get_file("test.txt")
        assert file is None

    def test_list_files(self, state: LocalSyncState) -> None:
        """Should list all tracked files."""
        state.mark_synced("a.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state.mark_synced("b.txt", server_file_id=2, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state.mark_synced("c.txt", server_file_id=3, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)

        files = state.list_files()
        assert len(files) == 3
        paths = [f.path for f in files]
        assert "a.txt" in paths
        assert "b.txt" in paths
        assert "c.txt" in paths


class TestDeriveStatus:
    """Tests for status derivation from disk state."""

    @pytest.fixture
    def base_path(self, tmp_path: Path) -> Path:
        """Create a base directory with some files."""
        sync_dir = tmp_path / "sync"
        sync_dir.mkdir()
        return sync_dir

    def test_derive_status_new_file(self, base_path: Path) -> None:
        """File on disk but not tracked should be NEW."""
        (base_path / "new.txt").write_text("content")

        status = derive_status("new.txt", tracked=None, base_path=base_path)
        assert status == FileStatus.NEW

    def test_derive_status_deleted_file(self, base_path: Path) -> None:
        """File tracked but not on disk should be DELETED."""
        tracked = SyncedFile(
            path="deleted.txt",
            local_mtime=100.0,
            local_size=50,
            server_version=1,
            chunk_hashes=[],
            synced_at=time.time(),
        )

        status = derive_status("deleted.txt", tracked=tracked, base_path=base_path)
        assert status == FileStatus.DELETED

    def test_derive_status_synced(self, base_path: Path) -> None:
        """File on disk matching tracked state should be SYNCED."""
        file_path = base_path / "synced.txt"
        file_path.write_text("content")
        stat = file_path.stat()

        tracked = SyncedFile(
            path="synced.txt",
            local_mtime=stat.st_mtime,
            local_size=stat.st_size,
            server_version=1,
            chunk_hashes=[],
            synced_at=time.time(),
        )

        status = derive_status("synced.txt", tracked=tracked, base_path=base_path)
        assert status == FileStatus.SYNCED

    def test_derive_status_modified_mtime(self, base_path: Path) -> None:
        """File with different mtime should be MODIFIED."""
        file_path = base_path / "modified.txt"
        file_path.write_text("content")
        stat = file_path.stat()

        tracked = SyncedFile(
            path="modified.txt",
            local_mtime=stat.st_mtime - 100,  # Older mtime
            local_size=stat.st_size,
            server_version=1,
            chunk_hashes=[],
            synced_at=time.time(),
        )

        status = derive_status("modified.txt", tracked=tracked, base_path=base_path)
        assert status == FileStatus.MODIFIED

    def test_derive_status_modified_size(self, base_path: Path) -> None:
        """File with different size should be MODIFIED."""
        file_path = base_path / "modified.txt"
        file_path.write_text("content")
        stat = file_path.stat()

        tracked = SyncedFile(
            path="modified.txt",
            local_mtime=stat.st_mtime,
            local_size=stat.st_size + 100,  # Different size
            server_version=1,
            chunk_hashes=[],
            synced_at=time.time(),
        )

        status = derive_status("modified.txt", tracked=tracked, base_path=base_path)
        assert status == FileStatus.MODIFIED

    def test_derive_status_none_when_nothing_exists(self, base_path: Path) -> None:
        """Should return None if file doesn't exist anywhere."""
        status = derive_status("nonexistent.txt", tracked=None, base_path=base_path)
        assert status is None


class TestBackwardsCompatibility:
    """Tests for backwards compatibility methods (no-ops)."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> LocalSyncState:
        """Create a SyncState instance."""
        s = LocalSyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_add_file_is_noop(self, state: LocalSyncState) -> None:
        """add_file should return placeholder but not persist."""
        file = state.add_file("test.txt", local_mtime=100.0, local_size=50)
        assert file.path == "test.txt"

        # Should not persist
        retrieved = state.get_file("test.txt")
        assert retrieved is None

    def test_mark_modified_is_noop(self, state: LocalSyncState) -> None:
        """mark_modified should be a no-op."""
        state.mark_modified("test.txt")  # Should not raise

    def test_mark_conflict_is_noop(self, state: LocalSyncState) -> None:
        """mark_conflict should be a no-op."""
        state.mark_conflict("test.txt")  # Should not raise

    def test_mark_deleted_removes_file(self, state: LocalSyncState) -> None:
        """mark_deleted should remove the file from tracking."""
        state.mark_synced("test.txt", server_file_id=1, server_version=1,
                          chunk_hashes=[], local_mtime=100.0, local_size=50)
        state.mark_deleted("test.txt")

        file = state.get_file("test.txt")
        assert file is None


class TestDeprecatedPendingUploads:
    """Tests for deprecated pending upload methods (no-ops)."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> LocalSyncState:
        """Create a SyncState instance."""
        s = LocalSyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_add_pending_upload_is_noop(self, state: LocalSyncState) -> None:
        """add_pending_upload should be a no-op."""
        state.add_pending_upload("test.txt")  # Should not raise

    def test_get_pending_uploads_returns_empty(self, state: LocalSyncState) -> None:
        """get_pending_uploads should return empty list."""
        result = state.get_pending_uploads()
        assert result == []

    def test_mark_upload_attempt_is_noop(self, state: LocalSyncState) -> None:
        """mark_upload_attempt should be a no-op."""
        state.mark_upload_attempt("test.txt", error="Error")  # Should not raise

    def test_remove_pending_upload_is_noop(self, state: LocalSyncState) -> None:
        """remove_pending_upload should be a no-op."""
        state.remove_pending_upload("test.txt")  # Should not raise

    def test_clear_pending_uploads_is_noop(self, state: LocalSyncState) -> None:
        """clear_pending_uploads should be a no-op."""
        state.clear_pending_uploads()  # Should not raise


class TestDeprecatedUploadProgress:
    """Tests for deprecated upload progress methods (no-ops)."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> LocalSyncState:
        """Create a SyncState instance."""
        s = LocalSyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_start_upload_progress_returns_none(self, state: LocalSyncState) -> None:
        """start_upload_progress should return None."""
        result = state.start_upload_progress("test.txt", ["hash1", "hash2"])
        assert result is None

    def test_get_upload_progress_returns_none(self, state: LocalSyncState) -> None:
        """get_upload_progress should return None."""
        result = state.get_upload_progress("test.txt")
        assert result is None

    def test_mark_chunk_uploaded_is_noop(self, state: LocalSyncState) -> None:
        """mark_chunk_uploaded should be a no-op."""
        state.mark_chunk_uploaded("test.txt", "hash1")  # Should not raise

    def test_clear_upload_progress_is_noop(self, state: LocalSyncState) -> None:
        """clear_upload_progress should be a no-op."""
        state.clear_upload_progress("test.txt")  # Should not raise

    def test_get_remaining_chunks_returns_empty(self, state: LocalSyncState) -> None:
        """get_remaining_chunks should return empty list."""
        result = state.get_remaining_chunks("test.txt")
        assert result == []

    def test_clear_all_upload_progress_is_noop(self, state: LocalSyncState) -> None:
        """clear_all_upload_progress should be a no-op."""
        state.clear_all_upload_progress()  # Should not raise


class TestSyncState:
    """Tests for sync state key-value storage."""

    @pytest.fixture
    def state(self, tmp_path: Path) -> LocalSyncState:
        """Create a SyncState instance."""
        s = LocalSyncState(tmp_path / "state.db")
        yield s
        s.close()

    def test_get_set_state(self, state: LocalSyncState) -> None:
        """Should store and retrieve state values."""
        state.set_state("my_key", "my_value")

        value = state.get_state("my_key")
        assert value == "my_value"

    def test_get_nonexistent_state(self, state: LocalSyncState) -> None:
        """Should return None for nonexistent key."""
        value = state.get_state("nonexistent")
        assert value is None

    def test_update_state(self, state: LocalSyncState) -> None:
        """Should update existing state."""
        state.set_state("key", "value1")
        state.set_state("key", "value2")

        value = state.get_state("key")
        assert value == "value2"

    def test_last_sync_at(self, state: LocalSyncState) -> None:
        """Should track last sync timestamp."""
        assert state.get_last_sync_at() is None

        state.set_last_sync_at(12345.67)
        assert state.get_last_sync_at() == 12345.67

    def test_last_server_version(self, state: LocalSyncState) -> None:
        """Should track last server version."""
        assert state.get_last_server_version() is None

        state.set_last_server_version(42)
        assert state.get_last_server_version() == 42

    def test_last_change_cursor(self, state: LocalSyncState) -> None:
        """Should track last change cursor."""
        assert state.get_last_change_cursor() is None

        state.set_last_change_cursor("2024-01-01T00:00:00Z")
        assert state.get_last_change_cursor() == "2024-01-01T00:00:00Z"


class TestFileStatus:
    """Tests for FileStatus enum."""

    def test_file_status_values(self) -> None:
        """FileStatus enum should have expected values."""
        assert FileStatus.SYNCED.value == "synced"
        assert FileStatus.MODIFIED.value == "modified"
        assert FileStatus.NEW.value == "new"
        assert FileStatus.DELETED.value == "deleted"
        assert FileStatus.CONFLICT.value == "conflict"


class TestSyncedFile:
    """Tests for SyncedFile dataclass."""

    def test_synced_file_creation(self) -> None:
        """Should create SyncedFile with all fields."""
        file = SyncedFile(
            path="test.txt",
            local_mtime=100.0,
            local_size=50,
            server_version=5,
            chunk_hashes=["hash1", "hash2"],
            synced_at=12345.0,
        )

        assert file.path == "test.txt"
        assert file.local_mtime == 100.0
        assert file.local_size == 50
        assert file.server_version == 5
        assert file.chunk_hashes == ["hash1", "hash2"]
        assert file.synced_at == 12345.0
