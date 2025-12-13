"""Tests for the SyncAgent HTTP client."""

from datetime import datetime

import pytest

from syncagent.client.api import (
    AuthenticationError,
    ConflictError,
    HTTPClient,
    NotFoundError,
    ServerFile,
    ServerMachine,
)
from syncagent.core.config import ServerConfig


def make_config(
    server_url: str = "http://test", token: str = "token123"
) -> ServerConfig:
    """Create a ServerConfig for testing."""
    return ServerConfig(server_url=server_url, token=token)


class TestServerFile:
    """Tests for ServerFile dataclass."""

    def test_from_dict(self) -> None:
        """Should create ServerFile from dictionary."""
        data = {
            "id": 1,
            "path": "docs/readme.txt",
            "size": 1024,
            "content_hash": "abc123",
            "version": 3,
            "created_at": "2025-01-01T10:00:00",
            "updated_at": "2025-01-02T15:30:00",
            "deleted_at": None,
        }

        file = ServerFile.from_dict(data)

        assert file.id == 1
        assert file.path == "docs/readme.txt"
        assert file.size == 1024
        assert file.content_hash == "abc123"
        assert file.version == 3
        assert file.created_at == datetime(2025, 1, 1, 10, 0, 0)
        assert file.updated_at == datetime(2025, 1, 2, 15, 30, 0)
        assert file.deleted_at is None

    def test_from_dict_with_deleted_at(self) -> None:
        """Should parse deleted_at when present."""
        data = {
            "id": 1,
            "path": "deleted.txt",
            "size": 100,
            "content_hash": "xyz",
            "version": 1,
            "created_at": "2025-01-01T10:00:00",
            "updated_at": "2025-01-02T15:30:00",
            "deleted_at": "2025-01-03T12:00:00",
        }

        file = ServerFile.from_dict(data)

        assert file.deleted_at == datetime(2025, 1, 3, 12, 0, 0)


class TestServerMachine:
    """Tests for ServerMachine dataclass."""

    def test_from_dict(self) -> None:
        """Should create ServerMachine from dictionary."""
        data = {
            "id": 42,
            "name": "laptop-julien",
            "platform": "windows",
            "created_at": "2025-01-01T10:00:00",
            "last_seen": "2025-01-02T15:30:00",
        }

        machine = ServerMachine.from_dict(data)

        assert machine.id == 42
        assert machine.name == "laptop-julien"
        assert machine.platform == "windows"
        assert machine.created_at == datetime(2025, 1, 1, 10, 0, 0)
        assert machine.last_seen == datetime(2025, 1, 2, 15, 30, 0)


class TestSyncClient:
    """Tests for SyncClient HTTP client."""

    @pytest.fixture
    def mock_server(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Set up mock server responses."""
        return httpx_mock

    def test_health_check_success(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should return True when server is healthy."""
        httpx_mock.add_response(url="http://test/health", json={"status": "ok"})

        with HTTPClient(make_config()) as client:
            assert client.health_check() is True

    def test_health_check_failure(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should return False when server is down."""
        httpx_mock.add_response(url="http://test/health", status_code=500)

        with HTTPClient(make_config()) as client:
            assert client.health_check() is False

    def test_list_files(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should list files from server."""
        httpx_mock.add_response(
            url="http://test/api/files",
            json=[
                {
                    "id": 1,
                    "path": "file1.txt",
                    "size": 100,
                    "content_hash": "hash1",
                    "version": 1,
                    "created_at": "2025-01-01T00:00:00",
                    "updated_at": "2025-01-01T00:00:00",
                    "deleted_at": None,
                },
                {
                    "id": 2,
                    "path": "file2.txt",
                    "size": 200,
                    "content_hash": "hash2",
                    "version": 2,
                    "created_at": "2025-01-02T00:00:00",
                    "updated_at": "2025-01-02T00:00:00",
                    "deleted_at": None,
                },
            ],
        )

        with HTTPClient(make_config()) as client:
            files = client.list_files()

        assert len(files) == 2
        assert files[0].path == "file1.txt"
        assert files[1].path == "file2.txt"

    def test_list_files_with_prefix(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should filter files by prefix."""
        httpx_mock.add_response(
            url="http://test/api/files?prefix=docs%2F",
            json=[
                {
                    "id": 1,
                    "path": "docs/readme.txt",
                    "size": 100,
                    "content_hash": "hash1",
                    "version": 1,
                    "created_at": "2025-01-01T00:00:00",
                    "updated_at": "2025-01-01T00:00:00",
                    "deleted_at": None,
                },
            ],
        )

        with HTTPClient(make_config()) as client:
            files = client.list_files(prefix="docs/")

        assert len(files) == 1
        assert files[0].path == "docs/readme.txt"

    def test_get_file(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should get file by path."""
        httpx_mock.add_response(
            url="http://test/api/files/docs/readme.txt",
            json={
                "id": 1,
                "path": "docs/readme.txt",
                "size": 1024,
                "content_hash": "abc123",
                "version": 3,
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-02T00:00:00",
                "deleted_at": None,
            },
        )

        with HTTPClient(make_config()) as client:
            file = client.get_file_metadata("docs/readme.txt")

        assert file.path == "docs/readme.txt"
        assert file.size == 1024

    def test_get_file_not_found(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should raise NotFoundError for missing file."""
        httpx_mock.add_response(
            url="http://test/api/files/missing.txt",
            status_code=404,
            json={"detail": "File not found"},
        )

        with HTTPClient(make_config()) as client, pytest.raises(NotFoundError):
            client.get_file_metadata("missing.txt")

    def test_create_file(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should create file on server."""
        httpx_mock.add_response(
            url="http://test/api/files",
            method="POST",
            status_code=201,
            json={
                "id": 5,
                "path": "new.txt",
                "size": 500,
                "content_hash": "newhash",
                "version": 1,
                "created_at": "2025-01-03T00:00:00",
                "updated_at": "2025-01-03T00:00:00",
                "deleted_at": None,
            },
        )

        with HTTPClient(make_config()) as client:
            file = client.create_file(
                path="new.txt",
                size=500,
                content_hash="newhash",
                chunks=["chunk1", "chunk2"],
            )

        assert file.id == 5
        assert file.path == "new.txt"
        assert file.version == 1

    def test_update_file(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should update file on server."""
        httpx_mock.add_response(
            url="http://test/api/files/existing.txt",
            method="PUT",
            json={
                "id": 1,
                "path": "existing.txt",
                "size": 1000,
                "content_hash": "updatedhash",
                "version": 4,
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-03T00:00:00",
                "deleted_at": None,
            },
        )

        with HTTPClient(make_config()) as client:
            file = client.update_file(
                path="existing.txt",
                size=1000,
                content_hash="updatedhash",
                parent_version=3,
                chunks=["chunk1"],
            )

        assert file.version == 4

    def test_update_file_conflict(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should raise ConflictError on version conflict."""
        httpx_mock.add_response(
            url="http://test/api/files/conflicted.txt",
            method="PUT",
            status_code=409,
            json={"detail": "Version conflict: expected 3, got 5"},
        )

        with (
            HTTPClient(make_config()) as client,
            pytest.raises(ConflictError, match="Version conflict"),
        ):
            client.update_file(
                path="conflicted.txt",
                size=100,
                content_hash="hash",
                parent_version=3,
                chunks=[],
            )

    def test_delete_file(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should delete file."""
        httpx_mock.add_response(
            url="http://test/api/files/todelete.txt",
            method="DELETE",
            status_code=204,
        )

        with HTTPClient(make_config()) as client:
            client.delete_file("todelete.txt")

    def test_get_file_chunks(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should get chunk hashes for file."""
        httpx_mock.add_response(
            url="http://test/api/chunks/myfile.txt",
            json=["chunk1hash", "chunk2hash", "chunk3hash"],
        )

        with HTTPClient(make_config()) as client:
            chunks = client.get_file_chunks("myfile.txt")

        assert chunks == ["chunk1hash", "chunk2hash", "chunk3hash"]

    def test_upload_chunk(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should upload chunk."""
        httpx_mock.add_response(
            url="http://test/api/storage/chunks/abc123",
            method="PUT",
            status_code=201,
        )

        with HTTPClient(make_config()) as client:
            client.upload_chunk("abc123", b"encrypted data")

    def test_download_chunk(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should download chunk."""
        chunk_data = b"encrypted chunk data"
        httpx_mock.add_response(
            url="http://test/api/storage/chunks/xyz789",
            content=chunk_data,
        )

        with HTTPClient(make_config()) as client:
            data = client.download_chunk("xyz789")

        assert data == chunk_data

    def test_download_chunk_not_found(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should raise NotFoundError for missing chunk."""
        httpx_mock.add_response(
            url="http://test/api/storage/chunks/missing",
            status_code=404,
            json={"detail": "Chunk not found"},
        )

        with HTTPClient(make_config()) as client, pytest.raises(NotFoundError):
            client.download_chunk("missing")

    def test_chunk_exists_true(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should return True when chunk exists."""
        httpx_mock.add_response(
            url="http://test/api/storage/chunks/exists123",
            method="HEAD",
            status_code=200,
        )

        with HTTPClient(make_config()) as client:
            assert client.chunk_exists("exists123") is True

    def test_chunk_exists_false(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should return False when chunk doesn't exist."""
        httpx_mock.add_response(
            url="http://test/api/storage/chunks/notfound",
            method="HEAD",
            status_code=404,
        )

        with HTTPClient(make_config()) as client:
            assert client.chunk_exists("notfound") is False

    def test_authentication_error(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should raise AuthenticationError on 401."""
        httpx_mock.add_response(
            url="http://test/api/files",
            status_code=401,
            json={"detail": "Invalid token"},
        )

        with HTTPClient(make_config(token="badtoken")) as client, pytest.raises(AuthenticationError):
            client.list_files()

    def test_list_machines(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should list machines."""
        httpx_mock.add_response(
            url="http://test/api/machines",
            json=[
                {
                    "id": 1,
                    "name": "laptop",
                    "platform": "windows",
                    "created_at": "2025-01-01T00:00:00",
                    "last_seen": "2025-01-02T00:00:00",
                },
            ],
        )

        with HTTPClient(make_config()) as client:
            machines = client.list_machines()

        assert len(machines) == 1
        assert machines[0].name == "laptop"

    def test_list_trash(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should list trash."""
        httpx_mock.add_response(
            url="http://test/api/trash",
            json=[
                {
                    "id": 1,
                    "path": "deleted.txt",
                    "size": 100,
                    "content_hash": "hash",
                    "version": 1,
                    "created_at": "2025-01-01T00:00:00",
                    "updated_at": "2025-01-01T00:00:00",
                    "deleted_at": "2025-01-02T00:00:00",
                },
            ],
        )

        with HTTPClient(make_config()) as client:
            files = client.list_trash()

        assert len(files) == 1
        assert files[0].deleted_at is not None

    def test_restore_file(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should restore file from trash."""
        httpx_mock.add_response(
            url="http://test/api/trash/deleted.txt/restore",
            method="POST",
            json={
                "id": 1,
                "path": "deleted.txt",
                "size": 100,
                "content_hash": "hash",
                "version": 1,
                "created_at": "2025-01-01T00:00:00",
                "updated_at": "2025-01-03T00:00:00",
                "deleted_at": None,
            },
        )

        with HTTPClient(make_config()) as client:
            file = client.restore_file("deleted.txt")

        assert file.deleted_at is None

    def test_context_manager(self) -> None:
        """Should work as context manager."""
        client = HTTPClient(make_config())
        with client as c:
            assert c is client
        # Client should be closed after context

    def test_server_url_trailing_slash(self, httpx_mock) -> None:  # type: ignore[no-untyped-def]
        """Should handle trailing slash in server URL."""
        httpx_mock.add_response(url="http://test/health", json={"status": "ok"})

        with HTTPClient(make_config(server_url="http://test/")) as client:
            assert client.health_check() is True
