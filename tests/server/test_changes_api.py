"""Tests for changes API endpoints."""

from __future__ import annotations

from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from syncagent.server.app import create_app
from syncagent.server.database import Database


@pytest.fixture
def db(tmp_path: Path) -> Generator[Database, None, None]:
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
def machine(db: Database):
    """Create a test machine."""
    return db.create_machine("test-machine", "Linux")


@pytest.fixture
def auth_headers(db: Database, machine) -> dict[str, str]:
    """Create auth headers with a valid token."""
    raw_token, _ = db.create_token(machine.id)
    return {"Authorization": f"Bearer {raw_token}"}


class TestGetChanges:
    """Tests for GET /api/changes endpoint."""

    def test_get_changes_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return empty list when no changes exist."""
        since = "2020-01-01T00:00:00Z"
        response = client.get(
            f"/api/changes?since={since}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert data["changes"] == []
        assert data["has_more"] is False
        assert data["latest_timestamp"] is None

    def test_get_changes_returns_recent(
        self, client: TestClient, db: Database, machine, auth_headers: dict[str, str]
    ) -> None:
        """Should return changes since specified timestamp."""
        # Create a file (which creates a change log entry)
        db.create_file("test.txt", 100, "hash1", machine.id)

        # Query for changes since a past date (use Z suffix for URL safety)
        since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = client.get(
            f"/api/changes?since={since}",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["changes"]) >= 1
        assert data["has_more"] is False

    def test_get_changes_respects_limit(
        self, client: TestClient, db: Database, machine, auth_headers: dict[str, str]
    ) -> None:
        """Should respect limit parameter."""
        # Create multiple files
        for i in range(5):
            db.create_file(f"file{i}.txt", 100, f"hash{i}", machine.id)

        since = (datetime.now(UTC) - timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        response = client.get(
            f"/api/changes?since={since}&limit=2",
            headers=auth_headers,
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["changes"]) == 2
        assert data["has_more"] is True

    def test_get_changes_requires_auth(self, client: TestClient) -> None:
        """Should require authentication."""
        since = "2020-01-01T00:00:00Z"
        response = client.get(f"/api/changes?since={since}")
        assert response.status_code == 401

    def test_get_changes_requires_since_param(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should require since parameter."""
        response = client.get("/api/changes", headers=auth_headers)
        assert response.status_code == 422  # Validation error


class TestGetLatestTimestamp:
    """Tests for GET /api/changes/latest endpoint."""

    def test_get_latest_timestamp_empty(
        self, client: TestClient, auth_headers: dict[str, str]
    ) -> None:
        """Should return null when no changes exist."""
        response = client.get("/api/changes/latest", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["latest_timestamp"] is None

    def test_get_latest_timestamp_with_changes(
        self, client: TestClient, db: Database, machine, auth_headers: dict[str, str]
    ) -> None:
        """Should return latest timestamp when changes exist."""
        # Create a file
        db.create_file("test.txt", 100, "hash1", machine.id)

        response = client.get("/api/changes/latest", headers=auth_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["latest_timestamp"] is not None
        # Verify it's a valid ISO timestamp
        datetime.fromisoformat(data["latest_timestamp"].replace("Z", "+00:00"))

    def test_get_latest_timestamp_requires_auth(self, client: TestClient) -> None:
        """Should require authentication."""
        response = client.get("/api/changes/latest")
        assert response.status_code == 401
