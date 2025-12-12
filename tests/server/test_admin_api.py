"""Tests for admin API endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import argon2
import pytest
from fastapi.testclient import TestClient

from syncagent.server.app import create_app
from syncagent.server.database import Database
from syncagent.server.storage import LocalFSStorage


@pytest.fixture
def db(tmp_path: Path) -> Database:
    """Create a test database."""
    db = Database(tmp_path / "test.db")
    yield db
    db.close()


@pytest.fixture
def storage(tmp_path: Path) -> LocalFSStorage:
    """Create a test storage."""
    return LocalFSStorage(tmp_path / "storage")


@pytest.fixture
def client(db: Database, storage: LocalFSStorage) -> TestClient:
    """Create a test client."""
    app = create_app(db, storage, trash_retention_days=30, enable_scheduler=False)
    return TestClient(app)


@pytest.fixture
def admin_session(db: Database, client: TestClient) -> str:
    """Create an admin user and return a session cookie."""
    # Create admin
    ph = argon2.PasswordHasher()
    password_hash = ph.hash("testpassword")
    db.create_admin("admin", password_hash)

    # Create session
    raw_token, _ = db.create_session()
    return raw_token


class TestPurgeTrashEndpoint:
    """Tests for POST /api/admin/purge-trash endpoint."""

    def test_requires_authentication(self, client: TestClient) -> None:
        """Should reject unauthenticated requests."""
        response = client.post("/api/admin/purge-trash")
        assert response.status_code == 401

    def test_requires_valid_session(self, client: TestClient, db: Database) -> None:
        """Should reject invalid session tokens."""
        # Create admin first
        ph = argon2.PasswordHasher()
        password_hash = ph.hash("testpassword")
        db.create_admin("admin", password_hash)

        response = client.post(
            "/api/admin/purge-trash",
            cookies={"session": "invalid-token"},
        )
        assert response.status_code == 401

    def test_purges_old_trash(
        self, client: TestClient, db: Database, storage: LocalFSStorage, admin_session: str
    ) -> None:
        """Should purge old trash items."""
        # Create a machine and file
        machine = db.create_machine("test", "Linux")
        db.create_file("old.txt", 100, "hash1", machine.id)
        db.set_file_chunks("old.txt", ["chunk1", "chunk2"])
        db.delete_file("old.txt", machine.id)

        # Make deletion date old
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "old.txt"),
            )
            conn.commit()

        # Store chunks
        storage.put("chunk1", b"data1")
        storage.put("chunk2", b"data2")

        # Purge
        response = client.post(
            "/api/admin/purge-trash",
            cookies={"session": admin_session},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["files_deleted"] == 1
        assert data["chunks_deleted"] == 2
        assert data["older_than_days"] == 30

        # Verify chunks were deleted from storage
        assert not storage.exists("chunk1")
        assert not storage.exists("chunk2")

    def test_custom_retention_days(
        self, client: TestClient, db: Database, storage: LocalFSStorage, admin_session: str
    ) -> None:
        """Should accept custom older_than_days parameter."""
        # Create a machine and file
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)
        db.set_file_chunks("test.txt", ["chunk1"])
        db.delete_file("test.txt", machine.id)

        # Make deletion date 10 days old
        old_date = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "test.txt"),
            )
            conn.commit()

        storage.put("chunk1", b"data")

        # Purge with 7 days retention
        response = client.post(
            "/api/admin/purge-trash",
            json={"older_than_days": 7},
            cookies={"session": admin_session},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["files_deleted"] == 1
        assert data["older_than_days"] == 7

    def test_empty_trash(
        self, client: TestClient, db: Database, admin_session: str
    ) -> None:
        """Should handle empty trash."""
        response = client.post(
            "/api/admin/purge-trash",
            cookies={"session": admin_session},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["files_deleted"] == 0
        assert data["chunks_deleted"] == 0

    def test_no_body_uses_default(
        self, client: TestClient, db: Database, admin_session: str
    ) -> None:
        """Should use default retention days when no body provided."""
        response = client.post(
            "/api/admin/purge-trash",
            cookies={"session": admin_session},
        )

        assert response.status_code == 200
        data = response.json()
        assert data["older_than_days"] == 30  # Default from create_app


class TestEmptyTrashWithStorage:
    """Tests for empty_trash web route with storage deletion."""

    def test_empty_trash_deletes_chunks_from_storage(
        self, client: TestClient, db: Database, storage: LocalFSStorage, admin_session: str
    ) -> None:
        """Should delete chunks from storage when emptying trash."""
        # Create a machine and file
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)
        db.set_file_chunks("test.txt", ["chunk1", "chunk2"])
        db.delete_file("test.txt", machine.id)

        # Store chunks
        storage.put("chunk1", b"data1")
        storage.put("chunk2", b"data2")

        # Empty trash via web route
        response = client.post(
            "/trash/empty",
            cookies={"session": admin_session},
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify chunks were deleted from storage
        assert not storage.exists("chunk1")
        assert not storage.exists("chunk2")


class TestPermanentlyDeleteFileWithStorage:
    """Tests for permanently_delete_file web route with storage deletion."""

    def test_delete_file_deletes_chunks_from_storage(
        self, client: TestClient, db: Database, storage: LocalFSStorage, admin_session: str
    ) -> None:
        """Should delete chunks from storage when permanently deleting file."""
        # Create a machine and file
        machine = db.create_machine("test", "Linux")
        file = db.create_file("test.txt", 100, "hash1", machine.id)
        db.set_file_chunks("test.txt", ["chunk1", "chunk2"])
        db.delete_file("test.txt", machine.id)

        # Store chunks
        storage.put("chunk1", b"data1")
        storage.put("chunk2", b"data2")

        # Permanently delete via web route
        response = client.post(
            f"/trash/{file.id}/delete",
            cookies={"session": admin_session},
            follow_redirects=False,
        )

        assert response.status_code == 302

        # Verify chunks were deleted from storage
        assert not storage.exists("chunk1")
        assert not storage.exists("chunk2")
