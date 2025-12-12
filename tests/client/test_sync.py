"""Tests for sync operations."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from syncagent.client.api import ConflictError, NotFoundError, ServerFile, SyncClient
from syncagent.client.state import FileStatus, SyncState
from syncagent.client.sync import (
    ConflictInfo,
    DownloadError,
    FileDownloader,
    FileUploader,
    SyncEngine,
    UploadError,
    generate_conflict_filename,
    get_machine_name,
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
        mock_client.create_file.return_value = MagicMock(
            id=1,
            version=1,
        )

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
        mock_client.update_file.return_value = MagicMock(
            id=1,
            version=3,
        )

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
        mock_client.create_file.return_value = MagicMock(id=1, version=1)

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
        """Should propagate conflict error."""
        test_file = tmp_path / "conflict.txt"
        test_file.write_text("Content")

        mock_client.chunk_exists.return_value = False
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
    """Tests for SyncEngine."""

    def test_push_new_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should push a new file to server."""
        base_path = tmp_path / "sync"
        base_path.mkdir()

        test_file = base_path / "new.txt"
        test_file.write_text("New file content")

        # Track the file locally
        sync_state.add_file("new.txt", status=FileStatus.NEW)

        mock_client.chunk_exists.return_value = False
        mock_client.get_file.side_effect = NotFoundError("Not found")
        server_response = MagicMock()
        server_response.id = 1
        server_response.version = 1
        mock_client.create_file.return_value = server_response
        mock_client.get_file_chunks.return_value = []

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.push_file("new.txt")

        assert result is not None
        assert result.server_file_id == 1

        # Should be marked as synced
        local_file = sync_state.get_file("new.txt")
        assert local_file is not None
        assert local_file.status == FileStatus.SYNCED

    def test_push_modified_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should push a modified file to server."""
        base_path = tmp_path / "sync"
        base_path.mkdir()

        test_file = base_path / "modified.txt"
        test_file.write_text("Modified content")

        # Track as existing file
        sync_state.add_file("modified.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("modified.txt", server_file_id=1, server_version=2)

        # Mock server file for conflict detection check
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "modified.txt"
        server_file.version = 2
        server_file.id = 1

        mock_client.chunk_exists.return_value = False
        mock_client.get_file.return_value = server_file
        mock_client.update_file.return_value = MagicMock(id=1, version=3)
        mock_client.get_file_chunks.return_value = []

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.push_file("modified.txt")

        assert result is not None
        assert result.server_version == 3
        mock_client.update_file.assert_called_once()

    def test_push_conflict(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should mark file as conflict when version mismatch and different content."""
        from syncagent.core.crypto import encrypt_chunk

        base_path = tmp_path / "sync"
        base_path.mkdir()

        test_file = base_path / "conflict.txt"
        test_file.write_text("Local changes")

        sync_state.add_file("conflict.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("conflict.txt", server_file_id=1, server_version=2)

        # Server file with different content hash
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "conflict.txt"
        server_file.size = 14
        server_file.version = 3
        server_file.id = 1
        server_file.content_hash = "different_hash"

        encrypted = encrypt_chunk(b"Server content", encryption_key)

        mock_client.chunk_exists.return_value = False
        mock_client.update_file.side_effect = ConflictError("Version conflict")
        mock_client.get_file.return_value = server_file
        mock_client.get_file_chunks.return_value = ["chunk1"]
        mock_client.download_chunk.return_value = encrypted

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.push_file("conflict.txt")

        assert result is None

        local_file = sync_state.get_file("conflict.txt")
        assert local_file is not None
        assert local_file.status == FileStatus.CONFLICT

    def test_pull_new_file(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should pull a new file from server."""
        from syncagent.core.crypto import encrypt_chunk

        base_path = tmp_path / "sync"
        base_path.mkdir()

        encrypted = encrypt_chunk(b"Server content", encryption_key)

        server_file = MagicMock(spec=ServerFile)
        server_file.path = "remote.txt"
        server_file.size = 14
        server_file.version = 1
        server_file.id = 1
        server_file.content_hash = "hash123"

        mock_client.get_file_chunks.return_value = ["chunk_hash"]
        mock_client.download_chunk.return_value = encrypted

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.pull_file(server_file)

        assert result.path == "remote.txt"
        assert (base_path / "remote.txt").exists()
        assert (base_path / "remote.txt").read_bytes() == b"Server content"

    def test_sync_pushes_and_pulls(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should sync both directions."""
        from syncagent.core.crypto import encrypt_chunk

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file to push
        local_file = base_path / "local.txt"
        local_file.write_text("Local content")
        sync_state.add_file("local.txt", status=FileStatus.NEW)

        # Mock server file to pull
        encrypted = encrypt_chunk(b"Remote content", encryption_key)
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "remote.txt"
        server_file.size = 14
        server_file.version = 1
        server_file.id = 2
        server_file.content_hash = "remotehash"

        mock_client.list_files.return_value = [server_file]
        mock_client.chunk_exists.return_value = False
        mock_client.get_file.side_effect = NotFoundError("Not found")
        server_response = MagicMock()
        server_response.id = 1
        server_response.version = 1
        mock_client.create_file.return_value = server_response
        mock_client.get_file_chunks.return_value = ["chunk_hash"]
        mock_client.download_chunk.return_value = encrypted

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.sync()

        assert "local.txt" in result.uploaded
        assert "remote.txt" in result.downloaded

    def test_sync_skips_up_to_date(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should skip files that are already in sync."""
        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Track file as already synced
        sync_state.add_file("synced.txt", status=FileStatus.SYNCED)
        sync_state.update_file("synced.txt", server_file_id=1, server_version=5)

        # Server has same version
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "synced.txt"
        server_file.version = 5
        server_file.id = 1

        mock_client.list_files.return_value = [server_file]

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.sync()

        assert len(result.downloaded) == 0
        mock_client.download_chunk.assert_not_called()

    def test_sync_skips_local_changes(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should not overwrite local changes with server version."""
        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file with changes
        local_file = base_path / "changed.txt"
        local_file.write_text("Local changes")

        sync_state.add_file("changed.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("changed.txt", server_file_id=1, server_version=2)

        # Server has newer version
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "changed.txt"
        server_file.version = 3
        server_file.id = 1

        # Mock upload - get_file is called for conflict detection
        mock_client.list_files.return_value = [server_file]
        mock_client.get_file.return_value = server_file
        mock_client.chunk_exists.return_value = False
        mock_client.update_file.return_value = MagicMock(id=1, version=4)
        mock_client.get_file_chunks.return_value = []

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.sync()

        # Should upload local, not download server
        assert "changed.txt" in result.uploaded
        assert "changed.txt" not in result.downloaded

    def test_conflict_with_same_hash_auto_resolves(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should auto-resolve when local and server have same content."""
        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file
        test_file = base_path / "same.txt"
        test_file.write_text("Same content")

        # Track as modified
        sync_state.add_file("same.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("same.txt", server_file_id=1, server_version=2)

        # Server file has same hash
        import hashlib
        content_hash = hashlib.sha256(b"Same content").hexdigest()

        server_file = MagicMock(spec=ServerFile)
        server_file.path = "same.txt"
        server_file.size = 12
        server_file.version = 3
        server_file.id = 1
        server_file.content_hash = content_hash

        # Simulate conflict error but same hash
        mock_client.chunk_exists.return_value = False
        mock_client.update_file.side_effect = ConflictError("Version conflict")
        mock_client.get_file.return_value = server_file
        mock_client.get_file_chunks.return_value = ["chunk1"]

        engine = SyncEngine(mock_client, sync_state, base_path, encryption_key)
        result = engine.push_file("same.txt")

        # Should auto-resolve (return result, not None)
        assert result is not None
        assert result.server_version == 3

        # File should be marked synced, not conflict
        local_file = sync_state.get_file("same.txt")
        assert local_file is not None
        assert local_file.status == FileStatus.SYNCED

    def test_real_conflict_creates_copy(
        self,
        tmp_path: Path,
        mock_client: MagicMock,
        sync_state: SyncState,
        encryption_key: bytes,
    ) -> None:
        """Should create conflict copy when content differs."""
        from syncagent.core.crypto import encrypt_chunk

        base_path = tmp_path / "sync"
        base_path.mkdir()

        # Create local file
        test_file = base_path / "different.txt"
        test_file.write_text("Local content")

        # Track as modified
        sync_state.add_file("different.txt", status=FileStatus.MODIFIED)
        sync_state.update_file("different.txt", server_file_id=1, server_version=2)

        # Server file has different hash
        server_file = MagicMock(spec=ServerFile)
        server_file.path = "different.txt"
        server_file.size = 14
        server_file.version = 3
        server_file.id = 1
        server_file.content_hash = "different_hash_from_server"

        # Mock download for server version
        encrypted = encrypt_chunk(b"Server content", encryption_key)

        mock_client.chunk_exists.return_value = False
        mock_client.update_file.side_effect = ConflictError("Version conflict")
        mock_client.get_file.return_value = server_file
        mock_client.get_file_chunks.return_value = ["chunk1"]
        mock_client.download_chunk.return_value = encrypted

        # Track conflict callback
        conflicts_received: list[ConflictInfo] = []

        def on_conflict(info: ConflictInfo) -> None:
            conflicts_received.append(info)

        engine = SyncEngine(
            mock_client, sync_state, base_path, encryption_key,
            conflict_callback=on_conflict,
        )
        result = engine.push_file("different.txt")

        # Should return None (conflict)
        assert result is None

        # Callback should have been called
        assert len(conflicts_received) == 1
        assert conflicts_received[0].original_path == "different.txt"
        assert "conflict-" in conflicts_received[0].conflict_path

        # Conflict file should exist
        conflict_files = list(base_path.glob("*.conflict-*"))
        assert len(conflict_files) == 1
        assert conflict_files[0].read_text() == "Local content"

        # Original file should have server content
        assert test_file.read_text() == "Server content"


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
