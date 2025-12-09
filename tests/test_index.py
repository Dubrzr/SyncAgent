"""Tests for local file index (SQLite)."""

from datetime import UTC, datetime
from pathlib import Path

import pytest

from syncagent.client.index import (
    FileEntry,
    FileIndex,
    FileState,
)


@pytest.fixture
def index(tmp_path: Path) -> FileIndex:
    """Create a test file index."""
    return FileIndex(tmp_path / "index.db")


class TestFileIndexCreation:
    """Tests for index creation and initialization."""

    def test_create_index_creates_db_file(self, tmp_path: Path) -> None:
        """Creating an index should create the SQLite database file."""
        db_path = tmp_path / "index.db"
        FileIndex(db_path)
        assert db_path.exists()

    def test_index_reopens_existing_db(self, tmp_path: Path) -> None:
        """Index should reopen existing database without error."""
        db_path = tmp_path / "index.db"
        index1 = FileIndex(db_path)
        index1.add_file(FileEntry(
            path="test.txt",
            size=100,
            mtime=datetime.now(UTC),
            state=FileState.SYNCED,
        ))
        index1.close()

        index2 = FileIndex(db_path)
        entry = index2.get_file("test.txt")
        assert entry is not None
        assert entry.size == 100


class TestFileEntryOperations:
    """Tests for file entry CRUD operations."""

    def test_add_and_get_file(self, index: FileIndex) -> None:
        """Should add and retrieve a file entry."""
        entry = FileEntry(
            path="docs/readme.txt",
            size=1024,
            mtime=datetime.now(UTC),
            state=FileState.SYNCED,
            content_hash="abc123",
        )
        index.add_file(entry)
        retrieved = index.get_file("docs/readme.txt")
        assert retrieved is not None
        assert retrieved.path == "docs/readme.txt"
        assert retrieved.size == 1024
        assert retrieved.content_hash == "abc123"

    def test_get_nonexistent_file_returns_none(self, index: FileIndex) -> None:
        """Getting a non-existent file should return None."""
        assert index.get_file("nonexistent.txt") is None

    def test_update_file(self, index: FileIndex) -> None:
        """Should update an existing file entry."""
        entry = FileEntry(
            path="test.txt",
            size=100,
            mtime=datetime.now(UTC),
            state=FileState.SYNCED,
        )
        index.add_file(entry)

        entry.size = 200
        entry.state = FileState.MODIFIED
        index.update_file(entry)

        retrieved = index.get_file("test.txt")
        assert retrieved is not None
        assert retrieved.size == 200
        assert retrieved.state == FileState.MODIFIED

    def test_delete_file(self, index: FileIndex) -> None:
        """Should delete a file entry."""
        entry = FileEntry(
            path="test.txt",
            size=100,
            mtime=datetime.now(UTC),
            state=FileState.SYNCED,
        )
        index.add_file(entry)
        index.delete_file("test.txt")
        assert index.get_file("test.txt") is None

    def test_delete_nonexistent_file_no_error(self, index: FileIndex) -> None:
        """Deleting a non-existent file should not raise error."""
        index.delete_file("nonexistent.txt")  # Should not raise


class TestFileQueries:
    """Tests for querying the index."""

    def test_list_all_files(self, index: FileIndex) -> None:
        """Should list all files in the index."""
        for i in range(5):
            index.add_file(FileEntry(
                path=f"file{i}.txt",
                size=i * 100,
                mtime=datetime.now(UTC),
                state=FileState.SYNCED,
            ))
        files = index.list_files()
        assert len(files) == 5

    def test_list_files_by_state(self, index: FileIndex) -> None:
        """Should filter files by state."""
        index.add_file(FileEntry(
            path="synced.txt", size=100, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.add_file(FileEntry(
            path="modified.txt", size=100, mtime=datetime.now(UTC), state=FileState.MODIFIED
        ))
        index.add_file(FileEntry(
            path="new.txt", size=100, mtime=datetime.now(UTC), state=FileState.NEW
        ))

        modified = index.list_files(state=FileState.MODIFIED)
        assert len(modified) == 1
        assert modified[0].path == "modified.txt"

    def test_list_files_in_directory(self, index: FileIndex) -> None:
        """Should list files in a specific directory."""
        index.add_file(FileEntry(
            path="docs/readme.txt", size=100, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.add_file(FileEntry(
            path="docs/guide.txt", size=100, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.add_file(FileEntry(
            path="src/main.py", size=100, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))

        docs_files = index.list_files(prefix="docs/")
        assert len(docs_files) == 2

    def test_get_pending_sync_files(self, index: FileIndex) -> None:
        """Should return files that need syncing."""
        index.add_file(FileEntry(
            path="synced.txt", size=100, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.add_file(FileEntry(
            path="modified.txt", size=100, mtime=datetime.now(UTC), state=FileState.MODIFIED
        ))
        index.add_file(FileEntry(
            path="new.txt", size=100, mtime=datetime.now(UTC), state=FileState.NEW
        ))
        index.add_file(FileEntry(
            path="deleted.txt", size=100, mtime=datetime.now(UTC), state=FileState.DELETED
        ))

        pending = index.get_pending_sync()
        assert len(pending) == 3
        states = {f.state for f in pending}
        assert FileState.SYNCED not in states


class TestChunkTracking:
    """Tests for chunk association with files."""

    def test_add_chunks_to_file(self, index: FileIndex) -> None:
        """Should associate chunks with a file."""
        index.add_file(FileEntry(
            path="large.bin", size=10_000_000, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        chunks = ["hash1", "hash2", "hash3"]
        index.set_file_chunks("large.bin", chunks)

        retrieved_chunks = index.get_file_chunks("large.bin")
        assert retrieved_chunks == chunks

    def test_get_chunks_preserves_order(self, index: FileIndex) -> None:
        """Chunk order should be preserved."""
        index.add_file(FileEntry(
            path="file.bin", size=1000, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        chunks = [f"hash{i}" for i in range(10)]
        index.set_file_chunks("file.bin", chunks)

        retrieved = index.get_file_chunks("file.bin")
        assert retrieved == chunks

    def test_update_file_chunks(self, index: FileIndex) -> None:
        """Should update chunks when file changes."""
        index.add_file(FileEntry(
            path="file.bin", size=1000, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.set_file_chunks("file.bin", ["old1", "old2"])
        index.set_file_chunks("file.bin", ["new1", "new2", "new3"])

        chunks = index.get_file_chunks("file.bin")
        assert chunks == ["new1", "new2", "new3"]

    def test_delete_file_removes_chunks(self, index: FileIndex) -> None:
        """Deleting a file should remove its chunks."""
        index.add_file(FileEntry(
            path="file.bin", size=1000, mtime=datetime.now(UTC), state=FileState.SYNCED
        ))
        index.set_file_chunks("file.bin", ["hash1", "hash2"])
        index.delete_file("file.bin")

        chunks = index.get_file_chunks("file.bin")
        assert chunks == []


class TestFileState:
    """Tests for FileState enum."""

    def test_file_states_exist(self) -> None:
        """All expected file states should exist."""
        assert FileState.NEW
        assert FileState.MODIFIED
        assert FileState.DELETED
        assert FileState.SYNCED
        assert FileState.CONFLICT


class TestFileEntry:
    """Tests for FileEntry dataclass."""

    def test_file_entry_attributes(self) -> None:
        """FileEntry should have all required attributes."""
        now = datetime.now(UTC)
        entry = FileEntry(
            path="test.txt",
            size=1024,
            mtime=now,
            state=FileState.SYNCED,
            content_hash="abc123",
            version=5,
        )
        assert entry.path == "test.txt"
        assert entry.size == 1024
        assert entry.mtime == now
        assert entry.state == FileState.SYNCED
        assert entry.content_hash == "abc123"
        assert entry.version == 5

    def test_file_entry_defaults(self) -> None:
        """FileEntry should have sensible defaults."""
        entry = FileEntry(
            path="test.txt",
            size=100,
            mtime=datetime.now(UTC),
            state=FileState.NEW,
        )
        assert entry.content_hash is None
        assert entry.version == 0
