"""Change scanner for detecting local and remote changes.

This module provides:
- ChangeScanner: Detects local/remote file changes
- emit_events(): Emits sync events to a queue based on detected changes

Architecture:
    ChangeScanner detects changes, emit_events() pushes them to the queue:
    1. Fetch remote changes via /api/changes (incremental) or list_files (fallback)
    2. Scan local filesystem for new/modified/deleted files
    3. Emit SyncEvent objects to EventQueue

    The actual sync work (upload/download/delete) is handled by:
    - SyncCoordinator: Processes events from the queue
    - Workers: Execute the transfers (UploadWorker, DownloadWorker, DeleteWorker)

    Flow: ChangeScanner → emit_events() → EventQueue → SyncCoordinator → Workers

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

    # Finally emit events to queue
    emit_events(queue, local_changes, remote_changes)
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
    LocalFileInfo,
    SyncEvent,
    SyncEventSource,
    SyncEventType,
    SyncResult,
)

if TYPE_CHECKING:
    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState

from syncagent.client.sync.queue import EventQueue

logger = logging.getLogger(__name__)

# Epoch timestamp for first sync
EPOCH = datetime(1970, 1, 1, tzinfo=UTC)


@dataclass
class LocalChanges:
    """Result of local filesystem scan.

    created/modified contain LocalFileInfo with mtime/size for deduplication.
    deleted contains just paths (no mtime needed for deletions).
    """

    created: list[LocalFileInfo]
    modified: list[LocalFileInfo]
    deleted: list[str]


@dataclass
class RemoteChanges:
    """Result of remote server scan."""

    created: list[str]
    modified: list[str]
    deleted: list[str]


def emit_events(
    queue: EventQueue,
    local_changes: LocalChanges,
    remote_changes: RemoteChanges,
) -> SyncResult:
    """Emit sync events to a queue based on detected changes.

    Detects conflicts when the same path has changes on both sides.
    Conflict resolution: local changes win (upload), remote skipped.

    Args:
        queue: Event queue to push events to.
        local_changes: Changes detected locally (with mtime/size metadata).
        remote_changes: Changes detected remotely.

    Returns:
        SyncResult summarizing what was queued.
    """
    # Build sets for conflict detection (extract paths from LocalFileInfo)
    local_created_set = {f.path for f in local_changes.created}
    local_modified_set = {f.path for f in local_changes.modified}
    local_deleted_set = set(local_changes.deleted)
    remote_created_set = set(remote_changes.created)
    remote_modified_set = set(remote_changes.modified)
    remote_deleted_set = set(remote_changes.deleted)

    # Detect real conflicts: both sides have content changes
    # - Local created/modified AND remote created/modified = conflict
    local_content_changes = local_created_set | local_modified_set
    remote_content_changes = remote_created_set | remote_modified_set
    conflict_paths = local_content_changes & remote_content_changes

    # Special cases (not conflicts - modification wins over deletion):
    # - Local deleted + Remote modified → remote wins (download)
    # - Local modified + Remote deleted → local wins (upload)
    local_deleted_remote_modified = local_deleted_set & remote_content_changes
    local_modified_remote_deleted = local_content_changes & remote_deleted_set

    conflicts: list[str] = []
    for path in conflict_paths:
        # Log conflict - will be resolved by worker (server wins, local preserved)
        logger.warning(f"Conflict detected for {path}: will be resolved during sync")
        conflicts.append(path)

    for path in local_deleted_remote_modified:
        logger.info(f"Remote modification wins over local deletion: {path}")

    for path in local_modified_remote_deleted:
        logger.info(f"Local modification wins over remote deletion: {path}")

    # Track what we queue
    uploaded: list[str] = []
    downloaded: list[str] = []
    deleted: list[str] = []

    # Push local events (with mtime/size metadata for deduplication)
    for file_info in local_changes.created:
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_CREATED,
            path=file_info.path,
            source=SyncEventSource.LOCAL,
            metadata={"mtime": file_info.mtime, "size": file_info.size},
        )
        queue.put(event)
        uploaded.append(file_info.path)
        logger.debug(f"Queued LOCAL_CREATED: {file_info.path}")

    for file_info in local_changes.modified:
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_MODIFIED,
            path=file_info.path,
            source=SyncEventSource.LOCAL,
            metadata={"mtime": file_info.mtime, "size": file_info.size},
        )
        queue.put(event)
        uploaded.append(file_info.path)
        logger.debug(f"Queued LOCAL_MODIFIED: {file_info.path}")

    for path in local_changes.deleted:
        # Skip if remote modification wins
        if path in local_deleted_remote_modified:
            logger.debug(f"Skipping LOCAL_DELETED (remote modification wins): {path}")
            continue
        event = SyncEvent.create(
            event_type=SyncEventType.LOCAL_DELETED,
            path=path,
            source=SyncEventSource.LOCAL,
        )
        queue.put(event)
        deleted.append(path)
        logger.debug(f"Queued LOCAL_DELETED: {path}")

    # Push remote events (skip conflicts - local won)
    for path in remote_changes.created:
        if path in conflict_paths:
            logger.debug(f"Skipping REMOTE_CREATED (conflict): {path}")
            continue
        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_CREATED,
            path=path,
            source=SyncEventSource.REMOTE,
        )
        queue.put(event)
        downloaded.append(path)
        logger.debug(f"Queued REMOTE_CREATED: {path}")

    for path in remote_changes.modified:
        if path in conflict_paths:
            logger.debug(f"Skipping REMOTE_MODIFIED (conflict): {path}")
            continue
        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_MODIFIED,
            path=path,
            source=SyncEventSource.REMOTE,
        )
        queue.put(event)
        downloaded.append(path)
        logger.debug(f"Queued REMOTE_MODIFIED: {path}")

    for path in remote_changes.deleted:
        if path in conflict_paths:
            logger.debug(f"Skipping REMOTE_DELETED (conflict): {path}")
            continue
        event = SyncEvent.create(
            event_type=SyncEventType.REMOTE_DELETED,
            path=path,
            source=SyncEventSource.REMOTE,
        )
        queue.put(event)
        # Remote deletions don't go in our deleted list (that's local deletions)
        logger.debug(f"Queued REMOTE_DELETED: {path}")

    return SyncResult(
        uploaded=uploaded,
        downloaded=downloaded,
        deleted=deleted,
        conflicts=conflicts,
        errors=[],
    )


class ChangeScanner:
    """Detects local and remote file changes.

    This class is responsible for:
    - Fetching remote changes from server (via /api/changes or list_files)
    - Scanning the local filesystem for changes
    """

    def __init__(
        self,
        http_client: HTTPClient,
        local_state: LocalSyncState,
        base_path: Path,
    ) -> None:
        """Initialize the change scanner.

        Args:
            http_client: HTTP client for server communication.
            local_state: Local state database.
            base_path: Base directory for synced files.
        """
        self._client = http_client
        self._state = local_state
        self._base_path = Path(base_path).resolve()

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
            LocalChanges with LocalFileInfo (including mtime/size) for created/modified,
            and paths for deleted.
        """
        created: list[LocalFileInfo] = []
        modified: list[LocalFileInfo] = []
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
                    created.append(LocalFileInfo(
                        path=relative_path,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    ))

                elif local_file.status == FileStatus.SYNCED:
                    # Check if modified since last sync
                    local_mtime = local_file.local_mtime or 0.0
                    if (
                        stat.st_mtime > local_mtime
                        or stat.st_size != local_file.local_size
                    ):
                        logger.debug(f"Found modified local file: {relative_path}")
                        self._state.mark_modified(relative_path)
                        modified.append(LocalFileInfo(
                            path=relative_path,
                            mtime=stat.st_mtime,
                            size=stat.st_size,
                        ))

                elif local_file.status in (FileStatus.NEW, FileStatus.MODIFIED):
                    # Already pending, add to list with current stats
                    file_info = LocalFileInfo(
                        path=relative_path,
                        mtime=stat.st_mtime,
                        size=stat.st_size,
                    )
                    if local_file.status == FileStatus.NEW:
                        created.append(file_info)
                    else:
                        modified.append(file_info)

        # Check for deleted files (in state DB but not on disk)
        synced_files = self._state.list_files(status=FileStatus.SYNCED)
        for local_file in synced_files:
            if local_file.path not in found_paths:
                # File was deleted locally
                logger.debug(f"Found deleted local file: {local_file.path}")
                self._state.mark_deleted(local_file.path)
                deleted.append(local_file.path)

        return LocalChanges(created=created, modified=modified, deleted=deleted)
