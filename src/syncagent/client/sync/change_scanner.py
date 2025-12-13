"""Change scanner for detecting local and remote changes.

This module provides:
- ChangeScanner: Scans local/remote for changes and pushes events to EventQueue

Architecture:
    ChangeScanner is an "event producer" that:
    1. Fetches remote changes via /api/changes (incremental) or list_files (fallback)
    2. Scans local filesystem for new/modified/deleted files
    3. Pushes SyncEvent objects to EventQueue

    The actual sync work (upload/download/delete) is handled by:
    - SyncCoordinator: Processes events from the queue
    - Workers: Execute the transfers (UploadWorker, DownloadWorker, DeleteWorker)

    Flow: ChangeScanner → EventQueue → SyncCoordinator → Workers

Usage with network resilience:
    # Fetch remote state first (with retry on network errors)
    while True:
        try:
            remote_changes = scanner.fetch_remote_changes()
            break
        except NetworkError:
            wait_for_network(client)

    # Then scan local (no network needed)
    local_changes = scanner.scan_local_changes()

    # Finally emit events
    scanner.emit_events(local_changes, remote_changes)
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
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


@dataclass
class LocalChanges:
    """Result of local filesystem scan."""

    created: list[str]
    modified: list[str]
    deleted: list[str]


@dataclass
class RemoteChanges:
    """Result of remote server scan."""

    created: list[str]
    modified: list[str]
    deleted: list[str]


class ChangeScanner:
    """Scans for local and remote changes and pushes events to the sync queue.

    This class is responsible for:
    - Fetching remote changes from server (via /api/changes or list_files)
    - Scanning the local filesystem for changes
    - Producing SyncEvent objects for the coordinator to process

    Usage (simple):
        queue = EventQueue()
        scanner = ChangeScanner(client, state, base_path, queue)
        result = scanner.scan()  # Does everything

    Usage (with network resilience):
        # Step 1: Fetch remote (can fail with network errors)
        remote = scanner.fetch_remote_changes()

        # Step 2: Scan local (no network, won't fail)
        local = scanner.scan_local_changes()

        # Step 3: Emit events to queue
        scanner.emit_events(local, remote)
    """

    def __init__(
        self,
        client: SyncClient,
        state: SyncState,
        base_path: Path,
        queue: EventQueue,
    ) -> None:
        """Initialize the change scanner.

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

    def fetch_remote_changes(self) -> RemoteChanges:
        """Fetch changes from the remote server.

        This method makes network calls and can raise network-related exceptions.
        Callers should handle ConnectionError, TimeoutError, OSError.

        Returns:
            RemoteChanges with lists of created, modified, deleted paths.

        Raises:
            ConnectionError, TimeoutError, OSError: On network failures.
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

        except (ConnectionError, TimeoutError, OSError):
            # Re-raise network errors for caller to handle
            raise
        except Exception as e:
            # Fall back to list_files if incremental sync fails for other reasons
            logger.warning(f"Incremental sync failed, falling back to full scan: {e}")
            return self._fetch_remote_changes_fallback()

        return RemoteChanges(created=created, modified=modified, deleted=deleted)

    def _fetch_remote_changes_fallback(self) -> RemoteChanges:
        """Fallback to full file list for remote changes.

        Used when incremental sync is not available or fails.

        Returns:
            RemoteChanges with lists of created, modified paths.
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
        return RemoteChanges(created=created, modified=modified, deleted=[])

    def scan_local_changes(self) -> LocalChanges:
        """Scan local filesystem for changes.

        This method does not make network calls and should not fail due to
        network issues.

        Returns:
            LocalChanges with lists of created, modified, deleted paths.
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

        return LocalChanges(created=created, modified=modified, deleted=deleted)

    def emit_events(
        self,
        local_changes: LocalChanges,
        remote_changes: RemoteChanges,
    ) -> SyncResult:
        """Emit sync events to the queue based on detected changes.

        Args:
            local_changes: Changes detected locally.
            remote_changes: Changes detected remotely.

        Returns:
            SyncResult summarizing what was queued.
        """
        # Push local events to queue
        for path in local_changes.created:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_CREATED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_CREATED: {path}")

        for path in local_changes.modified:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_MODIFIED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_MODIFIED: {path}")

        for path in local_changes.deleted:
            event = SyncEvent.create(
                event_type=SyncEventType.LOCAL_DELETED,
                path=path,
                source=SyncEventSource.LOCAL,
            )
            self._queue.put(event)
            logger.debug(f"Queued LOCAL_DELETED: {path}")

        # Push remote events to queue
        for path in remote_changes.created:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_CREATED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_CREATED: {path}")

        for path in remote_changes.modified:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_MODIFIED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_MODIFIED: {path}")

        for path in remote_changes.deleted:
            event = SyncEvent.create(
                event_type=SyncEventType.REMOTE_DELETED,
                path=path,
                source=SyncEventSource.REMOTE,
            )
            self._queue.put(event)
            logger.debug(f"Queued REMOTE_DELETED: {path}")

        # Return summary of what was queued
        return SyncResult(
            uploaded=local_changes.created + local_changes.modified,
            downloaded=remote_changes.created + remote_changes.modified,
            deleted=local_changes.deleted,
            conflicts=[],
            errors=[],
        )

    def scan(self) -> SyncResult:
        """Scan for changes and push events to the queue.

        This is a convenience method that:
        1. Fetches remote changes from server
        2. Scans local filesystem for changes
        3. Emits events to the queue

        For network-resilient operation, use the individual methods:
        fetch_remote_changes(), scan_local_changes(), emit_events()

        Returns:
            SyncResult with counts of events pushed (not completed transfers).
        """
        errors: list[str] = []

        # 1. Fetch remote changes (can fail with network errors)
        try:
            remote_changes = self.fetch_remote_changes()
        except Exception as e:
            logger.error(f"Error fetching remote changes: {e}")
            errors.append(f"Remote fetch error: {e}")
            remote_changes = RemoteChanges(created=[], modified=[], deleted=[])

        # 2. Scan local changes (no network, shouldn't fail)
        try:
            local_changes = self.scan_local_changes()
        except Exception as e:
            logger.error(f"Error scanning local changes: {e}")
            errors.append(f"Local scan error: {e}")
            local_changes = LocalChanges(created=[], modified=[], deleted=[])

        # 3. Emit events
        result = self.emit_events(local_changes, remote_changes)

        # Add any errors to result
        if errors:
            return SyncResult(
                uploaded=result.uploaded,
                downloaded=result.downloaded,
                deleted=result.deleted,
                conflicts=result.conflicts,
                errors=errors,
            )

        return result
