"""Tests for FastAPI server endpoints."""

from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient

from syncagent.server.app import create_app
from syncagent.server.database import Database


@pytest.fixture
def db(tmp_path) -> Generator[Database, None, None]:
    """Create a test database."""
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


@pytest.fixture
def client(db: Database) -> TestClient:
    """Create a test client with the app."""
    app = create_app(db)
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

    def test_register_machine(self, client: TestClient) -> None:
        """Should register a new machine and return token."""
        response = client.post(
            "/api/machines/register",
            json={"name": "my-laptop", "platform": "Windows"},
        )
        assert response.status_code == 201
        data = response.json()
        assert "token" in data
        assert data["token"].startswith("sa_")
        assert data["machine"]["name"] == "my-laptop"

    def test_register_duplicate_name_fails(self, client: TestClient) -> None:
        """Registering with duplicate name should fail."""
        client.post(
            "/api/machines/register",
            json={"name": "same-name", "platform": "Linux"},
        )
        response = client.post(
            "/api/machines/register",
            json={"name": "same-name", "platform": "macOS"},
        )
        assert response.status_code == 409

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
