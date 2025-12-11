"""Tests for FastAPI server endpoints."""

from collections.abc import Generator
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syncagent.server.app import create_app
from syncagent.server.database import Database
from syncagent.server.storage import LocalFSStorage


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
    """Create a test database."""
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalFSStorage:
    """Create a test storage."""
    return LocalFSStorage(tmp_path / "chunks")


@pytest.fixture
def client(db: Database) -> TestClient:
    """Create a test client with the app (no storage)."""
    app = create_app(db)
    return TestClient(app)


@pytest.fixture
def client_with_storage(db: Database, storage: LocalFSStorage) -> TestClient:
    """Create a test client with storage enabled."""
    app = create_app(db, storage)
    return TestClient(app)


@pytest.fixture
def auth_headers(db: Database) -> dict[str, str]:
    """Create auth headers with a valid token."""
    machine = db.create_machine("test-machine", "Linux")
    raw_token, _ = db.create_token(machine.id)
    return {"Authorization": f"Bearer {raw_token}"}


class TestHealthEndpoint:
    """Tests for health check endpoint."""

    def test_health_check(self, client: TestClient) -> None:
        """Health endpoint should return OK."""
        response = client.get("/health")
        assert response.status_code == 200
        assert response.json()["status"] == "ok"


class TestMachineEndpoints:
    """Tests for machine management endpoints."""

    def test_register_machine(self, client: TestClient, db: Database) -> None:
        """Should register a new machine and return token."""
        # Create an invitation first
        raw_invitation, _ = db.create_invitation()

        response = client.post(
            "/api/machines/register",
            json={
                "name": "my-laptop",
                "platform": "Windows",
                "invitation_token": raw_invitation,
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert data["token"].startswith("sa_")
        assert data["machine"]["name"] == "my-laptop"

    def test_register_duplicate_name_fails(self, client: TestClient, db: Database) -> None:
        """Registering with duplicate name should fail."""
        raw_invitation1, _ = db.create_invitation()
        raw_invitation2, _ = db.create_invitation()

        client.post(
            "/api/machines/register",
            json={
                "name": "same-name",
                "platform": "Linux",
                "invitation_token": raw_invitation1,
            },
        )
        response = client.post(
            "/api/machines/register",
            json={
                "name": "same-name",
                "platform": "macOS",
                "invitation_token": raw_invitation2,
            },
        )
        assert response.status_code == 409

    def test_register_invalid_invitation_fails(self, client: TestClient) -> None:
        """Registering with invalid invitation should fail."""
        response = client.post(
            "/api/machines/register",
            json={
                "name": "my-laptop",
                "platform": "Windows",
                "invitation_token": "invalid-token",
            },
        )
        assert response.status_code == 401

    def test_list_machines_requires_auth(self, client: TestClient) -> None:
        """Listing machines requires authentication."""
        response = client.get("/api/machines")
        assert response.status_code == 401

    def test_list_machines(
        self, client: TestClient, auth_headers: dict[str, str], db: Database
    ) -> None:
        """Should list all machines."""
        db.create_machine("machine2", "Windows")
        response = client.get("/api/machines", headers=auth_headers)
        assert response.status_code == 200
        machines = response.json()
        assert len(machines) >= 2

    def test_delete_machine(
        self, client: TestClient, auth_headers: dict[str, str], db: Database
    ) -> None:
        """Should delete a machine."""
        machine = db.create_machine("to-delete", "Linux")
        response = client.delete(
            f"/api/machines/{machine.id}",
            headers=auth_headers,
        )
        assert response.status_code == 204
        # Verify it's deleted
        assert db.get_machine(machine.id) is None

    def test_delete_machine_not_found(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for non-existent machine."""
        response = client.delete(
            "/api/machines/99999",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_machine_requires_auth(self, client: TestClient, db: Database) -> None:
        """Deleting machine requires authentication."""
        machine = db.create_machine("no-auth-delete", "Windows")
        response = client.delete(f"/api/machines/{machine.id}")
        assert response.status_code == 401


class TestAuthEndpoints:
    """Tests for authentication."""

    def test_invalid_token_rejected(self, client: TestClient) -> None:
        """Invalid token should be rejected."""
        response = client.get(
            "/api/machines",
            headers={"Authorization": "Bearer invalid_token"},
        )
        assert response.status_code == 401

    def test_missing_auth_rejected(self, client: TestClient) -> None:
        """Missing auth header should be rejected."""
        response = client.get("/api/files")
        assert response.status_code == 401

    def test_valid_token_accepted(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Valid token should be accepted."""
        response = client.get("/api/files", headers=auth_headers)
        assert response.status_code == 200


class TestFileEndpoints:
    """Tests for file metadata endpoints."""

    def test_create_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should create file metadata."""
        response = client.post(
            "/api/files",
            headers=auth_headers,
            json={
                "path": "docs/readme.txt",
                "size": 1024,
                "content_hash": "abc123def456",
                "chunks": ["chunk1", "chunk2"],
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["path"] == "docs/readme.txt"
        assert data["version"] == 1

    def test_get_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should get file metadata."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash", "chunks": []},
        )
        response = client.get("/api/files/test.txt", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["path"] == "test.txt"

    def test_get_nonexistent_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Getting non-existent file should return 404."""
        response = client.get("/api/files/nonexistent.txt", headers=auth_headers)
        assert response.status_code == 404

    def test_update_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should update file with version increment."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash1", "chunks": []},
        )
        response = client.put(
            "/api/files/test.txt",
            headers=auth_headers,
            json={
                "size": 200,
                "content_hash": "hash2",
                "parent_version": 1,
                "chunks": ["new_chunk"],
            },
        )
        assert response.status_code == 200
        assert response.json()["version"] == 2

    def test_update_file_conflict(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should detect conflicts on update."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash1", "chunks": []},
        )
        # First update succeeds
        client.put(
            "/api/files/test.txt",
            headers=auth_headers,
            json={"size": 200, "content_hash": "hash2", "parent_version": 1, "chunks": []},
        )
        # Second update with old version fails
        response = client.put(
            "/api/files/test.txt",
            headers=auth_headers,
            json={"size": 300, "content_hash": "hash3", "parent_version": 1, "chunks": []},
        )
        assert response.status_code == 409

    def test_list_files(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should list all files."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "file1.txt", "size": 100, "content_hash": "h1", "chunks": []},
        )
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "file2.txt", "size": 200, "content_hash": "h2", "chunks": []},
        )
        response = client.get("/api/files", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_delete_file(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should soft-delete a file."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash", "chunks": []},
        )
        response = client.delete("/api/files/test.txt", headers=auth_headers)
        assert response.status_code == 204

        # File should not appear in list
        list_response = client.get("/api/files", headers=auth_headers)
        assert len(list_response.json()) == 0


class TestTrashEndpoints:
    """Tests for trash management endpoints."""

    def test_list_trash(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should list deleted files."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash", "chunks": []},
        )
        client.delete("/api/files/test.txt", headers=auth_headers)

        response = client.get("/api/trash", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 1

    def test_restore_from_trash(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should restore a file from trash."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={"path": "test.txt", "size": 100, "content_hash": "hash", "chunks": []},
        )
        client.delete("/api/files/test.txt", headers=auth_headers)

        response = client.post("/api/trash/test.txt/restore", headers=auth_headers)
        assert response.status_code == 200

        # File should appear in list again
        list_response = client.get("/api/files", headers=auth_headers)
        assert len(list_response.json()) == 1


class TestChunkEndpoints:
    """Tests for chunk endpoints."""

    def test_get_file_chunks(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should get chunks for a file."""
        client.post(
            "/api/files",
            headers=auth_headers,
            json={
                "path": "large.bin",
                "size": 10000000,
                "content_hash": "hash",
                "chunks": ["chunk1", "chunk2", "chunk3"],
            },
        )
        response = client.get("/api/chunks/large.bin", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == ["chunk1", "chunk2", "chunk3"]


class TestChunkStorageEndpoints:
    """Tests for chunk storage (blob) endpoints."""

    def test_upload_chunk(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should upload a chunk."""
        chunk_hash = "a" * 64
        chunk_data = b"encrypted chunk data"

        response = client_with_storage.put(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
            content=chunk_data,
        )
        assert response.status_code == 201

    def test_download_chunk(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should download an uploaded chunk."""
        chunk_hash = "b" * 64
        chunk_data = b"test chunk content"

        # Upload first
        client_with_storage.put(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
            content=chunk_data,
        )

        # Download
        response = client_with_storage.get(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.content == chunk_data

    def test_download_missing_chunk(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 for missing chunk."""
        response = client_with_storage.get(
            "/api/storage/chunks/" + "c" * 64,
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_check_chunk_exists(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """HEAD should return 200 for existing chunk."""
        chunk_hash = "d" * 64

        # Upload first
        client_with_storage.put(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
            content=b"data",
        )

        response = client_with_storage.head(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
        )
        assert response.status_code == 200

    def test_check_chunk_not_exists(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """HEAD should return 404 for missing chunk."""
        response = client_with_storage.head(
            "/api/storage/chunks/" + "e" * 64,
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_chunk(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should delete an existing chunk."""
        chunk_hash = "f" * 64

        # Upload first
        client_with_storage.put(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
            content=b"data",
        )

        response = client_with_storage.delete(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
        )
        assert response.status_code == 204

        # Verify deleted
        response = client_with_storage.head(
            f"/api/storage/chunks/{chunk_hash}",
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_delete_missing_chunk(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 404 when deleting missing chunk."""
        response = client_with_storage.delete(
            "/api/storage/chunks/" + "0" * 64,
            headers=auth_headers,
        )
        assert response.status_code == 404

    def test_upload_empty_chunk_rejected(
        self, client_with_storage: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should reject empty chunk data."""
        response = client_with_storage.put(
            "/api/storage/chunks/" + "1" * 64,
            headers=auth_headers,
            content=b"",
        )
        assert response.status_code == 400

    def test_storage_requires_auth(self, client_with_storage: TestClient) -> None:
        """Storage endpoints require authentication."""
        chunk_hash = "2" * 64

        response = client_with_storage.put(
            f"/api/storage/chunks/{chunk_hash}",
            content=b"data",
        )
        assert response.status_code == 401

        response = client_with_storage.get(f"/api/storage/chunks/{chunk_hash}")
        assert response.status_code == 401

    def test_storage_not_configured(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return 503 when storage not configured."""
        response = client.put(
            "/api/storage/chunks/" + "3" * 64,
            headers=auth_headers,
            content=b"data",
        )
        assert response.status_code == 503
        assert "not configured" in response.json()["detail"]
