"""Tests for trash purge scheduler."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from syncagent.server.database import Database
from syncagent.server.scheduler import TrashPurgeScheduler, purge_trash_with_storage
from syncagent.server.storage import LocalFSStorage

if TYPE_CHECKING:
    pass


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


class TestPurgeTrashWithStorage:
    """Tests for purge_trash_with_storage function."""

    def test_purges_old_files(self, db: Database, storage: LocalFSStorage) -> None:
        """Should purge files older than retention period."""
        machine = db.create_machine("test", "Linux")
        db.create_file("old.txt", 100, "hash1", machine.id)
        db.set_file_chunks("old.txt", ["chunk1"])
        db.delete_file("old.txt", machine.id)

        # Make deletion date old
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "old.txt"),
            )
            conn.commit()

        # Store chunk in storage
        storage.put("chunk1", b"data")
        assert storage.exists("chunk1")

        # Purge
        files_deleted, chunks_deleted = purge_trash_with_storage(db, storage, 30)

        assert files_deleted == 1
        assert chunks_deleted == 1
        assert not storage.exists("chunk1")

    def test_keeps_recent_files(self, db: Database, storage: LocalFSStorage) -> None:
        """Should not purge files newer than retention period."""
        machine = db.create_machine("test", "Linux")
        db.create_file("recent.txt", 100, "hash1", machine.id)
        db.set_file_chunks("recent.txt", ["chunk1"])
        db.delete_file("recent.txt", machine.id)

        storage.put("chunk1", b"data")

        # Purge with 30 days retention (file just deleted today)
        files_deleted, chunks_deleted = purge_trash_with_storage(db, storage, 30)

        assert files_deleted == 0
        assert chunks_deleted == 0
        assert storage.exists("chunk1")

    def test_handles_no_storage(self, db: Database) -> None:
        """Should work without storage (storage=None)."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)
        db.set_file_chunks("test.txt", ["chunk1"])
        db.delete_file("test.txt", machine.id)

        # Make deletion date old
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "test.txt"),
            )
            conn.commit()

        # Purge with no storage
        files_deleted, chunks_deleted = purge_trash_with_storage(db, None, 30)

        assert files_deleted == 1
        assert chunks_deleted == 0  # No chunks deleted because no storage

    def test_handles_empty_trash(self, db: Database, storage: LocalFSStorage) -> None:
        """Should handle empty trash gracefully."""
        files_deleted, chunks_deleted = purge_trash_with_storage(db, storage, 30)

        assert files_deleted == 0
        assert chunks_deleted == 0


class TestTrashPurgeScheduler:
    """Tests for TrashPurgeScheduler class."""

    def test_init_default_values(self, db: Database, storage: LocalFSStorage) -> None:
        """Should initialize with default values."""
        scheduler = TrashPurgeScheduler(db, storage)

        assert scheduler._retention_days == 30
        assert scheduler._hour == 3
        assert scheduler._minute == 0
        assert scheduler._scheduler is None

    def test_init_custom_values(self, db: Database, storage: LocalFSStorage) -> None:
        """Should accept custom values."""
        scheduler = TrashPurgeScheduler(
            db, storage, retention_days=7, hour=2, minute=30
        )

        assert scheduler._retention_days == 7
        assert scheduler._hour == 2
        assert scheduler._minute == 30

    def test_start_creates_scheduler(self, db: Database, storage: LocalFSStorage) -> None:
        """Should create and start APScheduler on start()."""
        scheduler = TrashPurgeScheduler(db, storage)
        scheduler.start()

        try:
            assert scheduler._scheduler is not None
            assert scheduler._scheduler.running
        finally:
            scheduler.stop()

    def test_stop_stops_scheduler(self, db: Database, storage: LocalFSStorage) -> None:
        """Should stop scheduler on stop()."""
        scheduler = TrashPurgeScheduler(db, storage)
        scheduler.start()
        scheduler.stop()

        assert scheduler._scheduler is None

    def test_start_idempotent(self, db: Database, storage: LocalFSStorage) -> None:
        """Should be safe to call start() multiple times."""
        scheduler = TrashPurgeScheduler(db, storage)
        scheduler.start()
        sched1 = scheduler._scheduler
        scheduler.start()  # Second call should be ignored
        sched2 = scheduler._scheduler

        try:
            assert sched1 is sched2
        finally:
            scheduler.stop()

    def test_run_now(self, db: Database, storage: LocalFSStorage) -> None:
        """Should run purge immediately with run_now()."""
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)
        db.set_file_chunks("test.txt", ["chunk1"])
        db.delete_file("test.txt", machine.id)

        # Make deletion date old
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE files SET deleted_at = ? WHERE path = ?",
                (old_date, "test.txt"),
            )
            conn.commit()

        storage.put("chunk1", b"data")

        scheduler = TrashPurgeScheduler(db, storage, retention_days=30)
        files_deleted, chunks_deleted = scheduler.run_now()

        assert files_deleted == 1
        assert chunks_deleted == 1

    @patch("syncagent.server.scheduler.purge_trash_with_storage")
    def test_purge_job_handles_exception(
        self, mock_purge: MagicMock, db: Database, storage: LocalFSStorage
    ) -> None:
        """Should handle exceptions in purge job gracefully."""
        mock_purge.side_effect = Exception("Test error")

        scheduler = TrashPurgeScheduler(db, storage)

        # Should not raise
        scheduler._purge_job()

    def test_cleanup_changes_now(self, db: Database, storage: LocalFSStorage) -> None:
        """Should run change log cleanup immediately with cleanup_changes_now()."""
        # Create some changes
        machine = db.create_machine("test", "Linux")
        db.create_file("test.txt", 100, "hash1", machine.id)

        # Make change log entry old
        old_date = (datetime.now(UTC) - timedelta(days=31)).isoformat()
        with db._engine.connect() as conn:
            conn.exec_driver_sql(
                "UPDATE change_log SET timestamp = ?",
                (old_date,),
            )
            conn.commit()

        scheduler = TrashPurgeScheduler(db, storage, retention_days=30)
        deleted = scheduler.cleanup_changes_now()

        # At least one change should have been deleted
        assert deleted >= 1

    def test_cleanup_changes_job_handles_exception(
        self, db: Database, storage: LocalFSStorage
    ) -> None:
        """Should handle exceptions in change log cleanup job gracefully."""
        scheduler = TrashPurgeScheduler(db, storage)

        # Mock db method to raise
        with patch.object(db, "cleanup_old_changes", side_effect=Exception("Test error")):
            # Should not raise
            scheduler._cleanup_changes_job()
