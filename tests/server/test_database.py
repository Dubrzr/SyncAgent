"""Tests for server database models."""

from datetime import UTC, datetime, timedelta

import pytest

from syncagent.server.database import (
    Database,
    hash_token,
)


@pytest.fixture
def db(tmp_path) -> Database:
    """Create a test database."""
    database = Database(tmp_path / "test.db")
    yield database
    database.close()


class TestDatabaseCreation:
    """Tests for database initialization."""

    def test_creates_db_file(self, tmp_path) -> None:
        """Database should create SQLite file."""
        db_path = tmp_path / "test.db"
        db = Database(db_path)
        assert db_path.exists()
        db.close()

    def test_uses_wal_mode(self, tmp_path) -> None:
        """Database should use WAL mode for concurrency."""
        db = Database(tmp_path / "test.db")
        with db._engine.connect() as conn:
            result = conn.exec_driver_sql("PRAGMA journal_mode").fetchone()
        assert result is not None
        assert result[0].lower() == "wal"
        db.close()


class TestMachineOperations:
    """Tests for machine management."""

    def test_create_machine(self, db: Database) -> None:
        """Should create a new machine."""
        machine = db.create_machine("laptop-home", "Windows")
        assert machine.name == "laptop-home"
        assert machine.platform == "Windows"
        assert machine.id is not None

    def test_get_machine_by_id(self, db: Database) -> None:
        """Should retrieve machine by ID."""
        created = db.create_machine("test-machine", "Linux")
        retrieved = db.get_machine(created.id)
        assert retrieved is not None
        assert retrieved.name == "test-machine"

    def test_get_machine_by_name(self, db: Database) -> None:
        """Should retrieve machine by name."""
        db.create_machine("unique-name", "macOS")
        machine = db.get_machine_by_name("unique-name")
        assert machine is not None
        assert machine.platform == "macOS"

    def test_list_machines(self, db: Database) -> None:
        """Should list all machines."""
        db.create_machine("machine1", "Windows")
        db.create_machine("machine2", "Linux")
        machines = db.list_machines()
        assert len(machines) == 2

    def test_update_machine_last_seen(self, db: Database) -> None:
        """Should update machine last_seen timestamp."""
        machine = db.create_machine("test", "Linux")
        old_last_seen = machine.last_seen
        db.update_machine_last_seen(machine.id)
        updated = db.get_machine(machine.id)
        assert updated is not None
        assert updated.last_seen >= old_last_seen

    def test_machine_name_unique(self, db: Database) -> None:
        """Machine names should be unique."""
        from sqlalchemy.exc import IntegrityError

        db.create_machine("same-name", "Windows")
        with pytest.raises(IntegrityError):
            db.create_machine("same-name", "Linux")


class TestTokenOperations:
    """Tests for token management."""

    def test_create_token(self, db: Database) -> None:
        """Should create a token for a machine."""
        machine = db.create_machine("test", "Linux")
        raw_token, token = db.create_token(machine.id)
        assert raw_token.startswith("sa_")
        assert token.machine_id == machine.id
        assert token.token_hash != raw_token

    def test_validate_token(self, db: Database) -> None:
        """Should validate a correct token."""
        machine = db.create_machine("test", "Linux")
        raw_token, _ = db.create_token(machine.id)
        validated = db.validate_token(raw_token)
        assert validated is not None
        assert validated.machine_id == machine.id

    def test_invalid_token_returns_none(self, db: Database) -> None:
        """Invalid token should return None."""
        assert db.validate_token("invalid_token") is None

    def test_expired_token_returns_none(self, db: Database) -> None:
        """Expired token should return None."""
        machine = db.create_machine("test", "Linux")
        raw_token, token = db.create_token(machine.id, expires_in=timedelta(seconds=-1))
        assert db.validate_token(raw_token) is None

    def test_revoke_token(self, db: Database) -> None:
        """Should revoke a token."""
        machine = db.create_machine("test", "Linux")
        raw_token, token = db.create_token(machine.id)
        db.revoke_token(token.id)
        assert db.validate_token(raw_token) is None

    def test_token_hash_function(self) -> None:
        """hash_token should produce consistent SHA-256 hash."""
        token = "sa_test123"
        hash1 = hash_token(token)
        hash2 = hash_token(token)
        assert hash1 == hash2
        assert len(hash1) == 64  # SHA-256 hex


class TestFileMetadataOperations:
    """Tests for file metadata management."""

    def test_create_file(self, db: Database) -> None:
        """Should create file metadata."""
        machine = db.create_machine("test", "Linux")
        file = db.create_file(
            path="docs/readme.txt",
            size=1024,
            content_hash="abc123",
            machine_id=machine.id,
        )
        assert file.path == "docs/readme.txt"
        assert file.size == 1024
        assert file.version == 1

    def test_get_file(self, db: Database) -> None:
        """Should retrieve file by path."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash", machine.id)
        file = db.get_file("test.txt")
        assert file is not None
        assert file.size == 100

    def test_update_file_increments_version(self, db: Database) -> None:
        """Updating a file should increment version."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)
        db.update_file("test.txt", 200, "hash2", machine.id, parent_version=1)
        file = db.get_file("test.txt")
        assert file is not None
        assert file.version == 2
        assert file.size == 200

    def test_update_file_conflict_detection(self, db: Database) -> None:
        """Should detect conflicts when parent_version doesn't match."""
        machine1 = db.create_machine("machine1", "Linux")
        machine2 = db.create_machine("machine2", "Windows")
        db.create_file("test.txt", 100, "hash1", machine1.id)

        # Both try to update from version 1
        db.update_file("test.txt", 200, "hash2", machine1.id, parent_version=1)

        # machine2's update should fail - parent_version is now 2, not 1
        with pytest.raises(Exception, match="[Cc]onflict"):
            db.update_file("test.txt", 300, "hash3", machine2.id, parent_version=1)

    def test_list_files(self, db: Database) -> None:
        """Should list all files."""
        machine = db.create_machine("test", "Linux")
        db.create_file("file1.txt", 100, "h1", machine.id)
        db.create_file("file2.txt", 200, "h2", machine.id)
        files = db.list_files()
        assert len(files) == 2

    def test_list_files_with_prefix(self, db: Database) -> None:
        """Should filter files by prefix."""
        machine = db.create_machine("test", "Linux")
        db.create_file("docs/a.txt", 100, "h1", machine.id)
        db.create_file("docs/b.txt", 100, "h2", machine.id)
        db.create_file("src/c.py", 100, "h3", machine.id)
        docs = db.list_files(prefix="docs/")
        assert len(docs) == 2

    def test_delete_file(self, db: Database) -> None:
        """Should soft-delete a file (move to trash)."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash", machine.id)
        db.delete_file("test.txt", machine.id)
        file = db.get_file("test.txt")
        assert file is not None
        assert file.deleted_at is not None

    def test_list_trash(self, db: Database) -> None:
        """Should list deleted files."""
        machine = db.create_machine("test", "Linux")
        db.create_file("keep.txt", 100, "h1", machine.id)
        db.create_file("delete.txt", 100, "h2", machine.id)
        db.delete_file("delete.txt", machine.id)
        trash = db.list_trash()
        assert len(trash) == 1
        assert trash[0].path == "delete.txt"

    def test_restore_file(self, db: Database) -> None:
        """Should restore a deleted file."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash", machine.id)
        db.delete_file("test.txt", machine.id)
        db.restore_file("test.txt")
        file = db.get_file("test.txt")
        assert file is not None
        assert file.deleted_at is None

    def test_purge_trash(self, db: Database) -> None:
        """Should permanently delete old trash items."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash", machine.id)
        db.delete_file("test.txt", machine.id)
        # Force old deletion date using SQLAlchemy
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "test.txt"),
            )
            conn.commit()
        purged = db.purge_trash(older_than_days=30)
        assert purged == 1
        assert db.get_file("test.txt") is None


class TestChunkOperations:
    """Tests for chunk metadata."""

    def test_set_file_chunks(self, db: Database) -> None:
        """Should associate chunks with a file."""
        machine = db.create_machine("test", "Linux")
        db.create_file("large.bin", 1000000, "hash", machine.id)
        db.set_file_chunks("large.bin", ["chunk1", "chunk2", "chunk3"])
        chunks = db.get_file_chunks("large.bin")
        assert chunks == ["chunk1", "chunk2", "chunk3"]

    def test_chunks_order_preserved(self, db: Database) -> None:
        """Chunk order should be preserved."""
        machine = db.create_machine("test", "Linux")
        db.create_file("file.bin", 1000, "hash", machine.id)
        original = [f"chunk_{i}" for i in range(10)]
        db.set_file_chunks("file.bin", original)
        retrieved = db.get_file_chunks("file.bin")
        assert retrieved == original

    def test_update_chunks_replaces_old(self, db: Database) -> None:
        """Setting chunks should replace existing ones."""
        machine = db.create_machine("test", "Linux")
        db.create_file("file.bin", 1000, "hash", machine.id)
        db.set_file_chunks("file.bin", ["old1", "old2"])
        db.set_file_chunks("file.bin", ["new1"])
        chunks = db.get_file_chunks("file.bin")
        assert chunks == ["new1"]
