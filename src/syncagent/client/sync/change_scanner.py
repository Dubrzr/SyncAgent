"""Change scanner for detecting local and remote changes.

This module provides:
- ChangeScanner: Scans local/remote for changes and pushes events to EventQueue

Architecture:
    ChangeScanner is an "event producer" that:
    1. Scans local filesystem for new/modified/deleted files
    2. Fetches remote changes via /api/changes (incremental) or list_files (fallback)
    3. Pushes SyncEvent objects to EventQueue

    The actual sync work (upload/download/delete) is handled by:
    - SyncCoordinator: Processes events from the queue
    - Workers: Execute the transfers (UploadWorker, DownloadWorker, DeleteWorker)

    Flow: ChangeScanner → EventQueue → SyncCoordinator → Workers
"""

from __future__ import annotations

import logging
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.state import FileStatus
from syncagent.client.sync.ignore import IgnorePatterns
from syncagent.client.sync.types import (
    SyncEvent,
    SyncEventSource,
    SyncEventType,
    SyncResult,
)

if TYPE_CHECKING:
    from syncagent.client.api import SyncClient
    from syncagent.client.state import SyncState
    from syncagent.client.sync.queue import EventQueue

logger = logging.getLogger(__name__)

# Epoch timestamp for first sync
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


class ChangeScanner:
    """Scans for local and remote changes and pushes events to the sync queue.

    This class is responsible for:
    - Scanning the local filesystem for changes
    - Fetching remote changes from server (via /api/changes or list_files)
    - Producing SyncEvent objects for the coordinator to process

    Usage:
        queue = EventQueue()
        scanner = ChangeScanner(client, state, base_path, queue)

        # Scan and push events (non-blocking)
        result = scanner.scan()

        # Events are now in the queue, ready for coordinator to process
    """

    def __init__(
        self,
        client: SyncClient,
        state: SyncState,
        base_path: Path,
        queue: EventQueue,
    ) -> None:
        """Initialize the sync engine.

        Args:
            client: HTTP client for server communication.
            state: Local state database.
            base_path: Base directory for synced files.
            queue: Event queue to push events to.
        """
        self._client = client
        self._state = state
        self._base_path = Path(base_path).resolve()
        self._queue = queue

    def scan(self) -> SyncResult:
        """Scan for changes and push events to the queue.

        This method:
        1. Scans local folder for new/modified/deleted files
        2. Fetches server files and detects remote changes
        3. Pushes SyncEvent objects to the queue

        Returns:
            SyncResult with counts of events pushed (not completed transfers).
        """
        # Track events pushed
        local_created: list[str] = []
        local_modified: list[str] = []
        local_deleted: list[str] = []
        remote_created: list[str] = []
        remote_modified: list[str] = []
        remote_deleted: list[str] = []
        errors: list[str] = []

        # 1. Scan local folder for changes
        try:
            local_changes = self._scan_local_changes()
            local_created = local_changes["created"]
            local_modified = local_changes["modified"]
            local_deleted = local_changes["deleted"]
        except Exception as e:
            logger.error(f"Error scanning local changes: {e}")
            errors.append(f"Local scan error: {e}")

        # 2. Push local events to queue
        for path in local_created:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_CREATED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_CREATED: {path}")

        for path in local_modified:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_MODIFIED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_MODIFIED: {path}")

        for path in local_deleted:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_DELETED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_DELETED: {path}")

        # 3. Scan remote for changes
        try:
            remote_changes = self._scan_remote_changes()
            remote_created = remote_changes["created"]
            remote_modified = remote_changes["modified"]
            remote_deleted = remote_changes.get("deleted", [])
        except Exception as e:
            logger.error(f"Error scanning remote changes: {e}")
            errors.append(f"Remote scan error: {e}")

        # 4. Push remote events to queue
        for path in remote_created:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_CREATED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_CREATED: {path}")

        for path in remote_modified:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_MODIFIED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_MODIFIED: {path}")

        for path in remote_deleted:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_DELETED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_DELETED: {path}")

        # Return summary of what was queued
        return SyncResult(
            uploaded=local_created + local_modified,  # Will be uploaded
            downloaded=remote_created + remote_modified,  # Will be downloaded
            deleted=local_deleted,  # Will be deleted on server
            conflicts=[],  # Conflicts detected by coordinator
            errors=errors,
        )

    def _scan_local_changes(self) -> dict[str, list[str]]:
        """Scan local folder for new, modified, or deleted files.

        Returns:
            Dict with 'created', 'modified', and 'deleted' path lists.
        """
        created: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        # Use ignore patterns
        ignore = IgnorePatterns()
        syncignore_path = self._base_path / ".syncignore"
        ignore.load_from_file(syncignore_path)

        # Track files found on disk
        found_paths: set[str] = set()

        # Walk the directory
        for root_str, dirs, files in os.walk(self._base_path):
            root = Path(root_str)

            # Filter out ignored directories (including symlinks)
            dirs[:] = [
                d for d in dirs
                if not ignore.should_ignore(root / d, self._base_path)
            ]

            for filename in files:
                file_path = root / filename

                # Skip symlinks and ignored patterns
                if file_path.is_symlink() or ignore.should_ignore(file_path, self._base_path):
                    continue

                relative_path = str(file_path.relative_to(self._base_path))
                # Normalize path separators
                relative_path = relative_path.replace("\\", "/")
                found_paths.add(relative_path)

                local_file = self._state.get_file(relative_path)
                stat = file_path.stat()

                if local_file is None:
                    # New file
                    logger.debug(f"Found new local file: {relative_path}")
                    self._state.add_file(
                        relative_path,
                        local_mtime=stat.st_mtime,
                        local_size=stat.st_size,
                        local_hash="",  # Will be computed on upload
                        status=FileStatus.NEW,
                    )
                    created.append(relative_path)

                elif local_file.status == FileStatus.SYNCED:
                    # Check if modified since last sync
                    local_mtime = local_file.local_mtime or 0.0
                    if (
                        stat.st_mtime > local_mtime
                        or stat.st_size != local_file.local_size
                    ):
                        logger.debug(f"Found modified local file: {relative_path}")
                        self._state.mark_modified(relative_path)
                        modified.append(relative_path)

                elif local_file.status in (FileStatus.NEW, FileStatus.MODIFIED):
                    # Already pending, add to list
                    if local_file.status == FileStatus.NEW:
                        created.append(relative_path)
                    else:
                        modified.append(relative_path)

        # Check for deleted files (in state DB but not on disk)
        synced_files = self._state.list_files(status=FileStatus.SYNCED)
        for local_file in synced_files:
            if local_file.path not in found_paths:
                # File was deleted locally
                logger.debug(f"Found deleted local file: {local_file.path}")
                self._state.mark_deleted(local_file.path)
                deleted.append(local_file.path)

        return {"created": created, "modified": modified, "deleted": deleted}

    def _scan_remote_changes(self) -> dict[str, list[str]]:
        """Scan remote server for new, modified, or deleted files.

        Uses incremental sync via /api/changes when available.
        Falls back to list_files for first sync or if incremental fails.

        Returns:
            Dict with 'created', 'modified', and 'deleted' path lists.
        """
        created: list[str] = []
        modified: list[str] = []
        deleted: list[str] = []

        # Get the last change cursor
        cursor = self._state.get_last_change_cursor()

        try:
            # Try incremental sync via /api/changes
            since = datetime.fromisoformat(cursor) if cursor else EPOCH
            result = self._client.get_changes(since)

            for change in result.changes:
                local_file = self._state.get_file(change.file_path)

                # Skip if local has unsynced changes
                if local_file and local_file.status in (
                    FileStatus.MODIFIED,
                    FileStatus.NEW,
                    FileStatus.CONFLICT,
                ):
                    logger.debug(
                        f"Skipping remote {change.action} for {change.file_path}: local changes pending"
                    )
                    continue

                if change.action == "CREATED":
                    if local_file is None:
                        created.append(change.file_path)
                elif change.action == "UPDATED":
                    if local_file and local_file.server_version != change.version:
                        modified.append(change.file_path)
                    elif local_file is None:
                        # File was updated but we don't have it locally
                        created.append(change.file_path)
                elif change.action == "DELETED":
                    deleted.append(change.file_path)

            # Update cursor if we got changes
            if result.latest_timestamp:
                self._state.set_last_change_cursor(result.latest_timestamp.isoformat())

            logger.debug(
                f"Incremental sync: {len(result.changes)} changes "
                f"(created={len(created)}, modified={len(modified)}, deleted={len(deleted)})"
            )

        except Exception as e:
            # Fall back to list_files if incremental sync fails
            logger.warning(f"Incremental sync failed, falling back to full scan: {e}")
            return self._scan_remote_changes_fallback()

        return {"created": created, "modified": modified, "deleted": deleted}

    def _scan_remote_changes_fallback(self) -> dict[str, list[str]]:
        """Fallback to full file list for remote changes.

        Used when incremental sync is not available or fails.

        Returns:
            Dict with 'created', 'modified', and 'deleted' path lists.
        """
        created: list[str] = []
        modified: list[str] = []

        # Get all server files
        server_files = self._client.list_files()

        for server_file in server_files:
            local_file = self._state.get_file(server_file.path)

            if local_file is None:
                # New file on server
                created.append(server_file.path)

            elif local_file.server_version != server_file.version:
                # Skip if local has unsynced changes (will be handled as conflict by coordinator)
                if local_file.status in (
                    FileStatus.MODIFIED,
                    FileStatus.NEW,
                    FileStatus.CONFLICT,
                ):
                    logger.debug(
                        f"Skipping remote change for {server_file.path}: local changes pending"
                    )
                    continue

                # Modified on server
                modified.append(server_file.path)

        # Note: fallback doesn't detect remote deletions - need incremental for that
        return {"created": created, "modified": modified, "deleted": []}
