"""Scheduler for automatic maintenance tasks.

This module provides:
- Automatic daily trash purge at 3:00 AM
- Automatic daily change_log cleanup at 3:30 AM
- Manual purge functions for CLI/API usage
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger

if TYPE_CHECKING:
    from syncagent.server.database import Database
    from syncagent.server.storage import ChunkStorage

logger = logging.getLogger(__name__)


def purge_trash_with_storage(
    db: Database,
    storage: ChunkStorage | None,
    older_than_days: int = 30,
) -> tuple[int, int]:
    """Purge old trash items and delete their chunks from storage.

    Args:
        db: Database instance.
        storage: Chunk storage instance (may be None).
        older_than_days: Delete items older than this many days.

    Returns:
        Tuple of (files_deleted, chunks_deleted).
    """
    # Delete from database and get chunk hashes
    files_deleted, chunk_hashes = db.purge_trash(older_than_days)

    # Delete chunks from storage
    chunks_deleted = 0
    if storage and chunk_hashes:
        for chunk_hash in chunk_hashes:
            if storage.delete(chunk_hash):
                chunks_deleted += 1

    if files_deleted > 0:
        logger.info(
            "Trash purge completed: %d files deleted, %d chunks removed from storage",
            files_deleted,
            chunks_deleted,
        )
    else:
        logger.debug("Trash purge: no items older than %d days", older_than_days)

    return files_deleted, chunks_deleted


class TrashPurgeScheduler:
    """Scheduler for automatic maintenance tasks.

    Runs daily:
    - Trash purge at 3:00 AM
    - Change log cleanup at 3:30 AM
    """

    def __init__(
        self,
        db: Database,
        storage: ChunkStorage | None,
        retention_days: int = 30,
        hour: int = 3,
        minute: int = 0,
    ) -> None:
        """Initialize the scheduler.

        Args:
            db: Database instance.
            storage: Chunk storage instance.
            retention_days: Number of days to retain trash items and change log.
            hour: Hour to run the purge job (0-23).
            minute: Minute to run the purge job (0-59).
        """
        self._db = db
        self._storage = storage
        self._retention_days = retention_days
        self._hour = hour
        self._minute = minute
        self._scheduler: BackgroundScheduler | None = None

    def _purge_job(self) -> None:
        """Job function for scheduled trash purge."""
        logger.info("Starting scheduled trash purge (retention: %d days)", self._retention_days)
        try:
            purge_trash_with_storage(self._db, self._storage, self._retention_days)
        except Exception:
            logger.exception("Error during scheduled trash purge")

    def _cleanup_changes_job(self) -> None:
        """Job function for scheduled change log cleanup."""
        logger.info(
            "Starting scheduled change log cleanup (retention: %d days)",
            self._retention_days,
        )
        try:
            deleted = self._db.cleanup_old_changes(self._retention_days)
            if deleted > 0:
                logger.info("Change log cleanup: %d old entries deleted", deleted)
            else:
                logger.debug(
                    "Change log cleanup: no entries older than %d days",
                    self._retention_days,
                )
        except Exception:
            logger.exception("Error during scheduled change log cleanup")

    def start(self) -> None:
        """Start the scheduler."""
        if self._scheduler is not None:
            return  # Already running

        self._scheduler = BackgroundScheduler()

        # Schedule daily trash purge at specified time
        trash_trigger = CronTrigger(hour=self._hour, minute=self._minute)
        self._scheduler.add_job(
            self._purge_job,
            trigger=trash_trigger,
            id="trash_purge",
            name="Daily trash purge",
            replace_existing=True,
        )

        # Schedule daily change log cleanup 30 minutes later
        changes_trigger = CronTrigger(hour=self._hour, minute=self._minute + 30)
        self._scheduler.add_job(
            self._cleanup_changes_job,
            trigger=changes_trigger,
            id="change_log_cleanup",
            name="Daily change log cleanup",
            replace_existing=True,
        )

        self._scheduler.start()
        logger.info(
            "Trash purge scheduler started (daily at %02d:%02d, retention: %d days)",
            self._hour,
            self._minute,
            self._retention_days,
        )

    def stop(self) -> None:
        """Stop the scheduler."""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("Trash purge scheduler stopped")

    def run_now(self) -> tuple[int, int]:
        """Run the trash purge immediately (manual trigger).

        Returns:
            Tuple of (files_deleted, chunks_deleted).
        """
        return purge_trash_with_storage(self._db, self._storage, self._retention_days)

    def cleanup_changes_now(self) -> int:
        """Run the change log cleanup immediately (manual trigger).

        Returns:
            Number of change log entries deleted.
        """
        return self._db.cleanup_old_changes(self._retention_days)
