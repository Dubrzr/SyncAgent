"""Sync engine coordinating file synchronization.

This module provides:
- SyncEngine: Coordinates push/pull synchronization between local and server
"""

from __future__ import annotations

import contextlib
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.api import ConflictError, NotFoundError
from syncagent.client.state import FileStatus
from syncagent.client.sync.conflict import generate_conflict_filename, get_machine_name
from syncagent.client.sync.download import FileDownloader
from syncagent.client.sync.types import (
    ConflictCallback,
    ConflictInfo,
    DownloadResult,
    ProgressCallback,
    SyncResult,
    UploadResult,
)
from syncagent.client.sync.upload import FileUploader
from syncagent.core.crypto import compute_file_hash

if TYPE_CHECKING:
    from syncagent.client.api import ServerFile, SyncClient
    from syncagent.client.state import SyncState

logger = logging.getLogger(__name__)


class SyncEngine:
    """Coordinates file synchronization between local and server."""

    def __init__(
        self,
        client: SyncClient,
        state: SyncState,
        base_path: Path,
        encryption_key: bytes,
        progress_callback: ProgressCallback | None = None,
        conflict_callback: ConflictCallback | None = None,
    ) -> None:
        """Initialize the sync engine.

        Args:
            client: HTTP client for server communication.
            state: Local state database.
            base_path: Base directory for synced files.
            encryption_key: 32-byte AES key for encryption.
            progress_callback: Optional callback for progress updates.
            conflict_callback: Optional callback when conflicts are detected.
        """
        self._client = client
        self._state = state
        self._base_path = Path(base_path).resolve()
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._conflict_callback = conflict_callback
        # Pass state to uploader for resume capability
        self._uploader = FileUploader(
            client, encryption_key, progress_callback, state=state
        )
        self._downloader = FileDownloader(client, encryption_key, progress_callback)
        self._machine_name = get_machine_name()

    def sync(self) -> SyncResult:
        """Perform a full sync operation.

        Returns:
            SyncResult with lists of uploaded, downloaded, deleted, and conflict files.
        """
        uploaded: list[str] = []
        downloaded: list[str] = []
        deleted: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []

        # 0. Scan local folder for new/modified/deleted files
        self._scan_local_changes()

        # 1. Push local changes to server (including deletions)
        push_result = self._push_changes()
        uploaded.extend(push_result["uploaded"])
        deleted.extend(push_result["deleted"])
        conflicts.extend(push_result["conflicts"])
        errors.extend(push_result["errors"])

        # 2. Pull remote changes from server
        pull_result = self._pull_changes()
        downloaded.extend(pull_result["downloaded"])
        errors.extend(pull_result["errors"])

        return SyncResult(
            uploaded=uploaded,
            downloaded=downloaded,
            deleted=deleted,
            conflicts=conflicts,
            errors=errors,
        )

    def push_file(self, relative_path: str) -> UploadResult | None:
        """Push a single file to the server.

        Args:
            relative_path: Relative path of the file.

        Returns:
            UploadResult if successful, None if conflict.
        """
        local_path = self._base_path / relative_path
        local_file = self._state.get_file(relative_path)

        parent_version = None
        server_file: ServerFile | None = None

        if local_file and local_file.server_version:
            parent_version = local_file.server_version
            # Also fetch server file for conflict detection
            with contextlib.suppress(NotFoundError):
                server_file = self._client.get_file(relative_path)
        else:
            # Check if file exists on server (handles case where local state is out of sync)
            try:
                server_file = self._client.get_file(relative_path)
                parent_version = server_file.version
                logger.debug(f"File {relative_path} exists on server with version {parent_version}")
            except NotFoundError:
                # File truly doesn't exist on server, will be created
                pass

        try:
            result = self._uploader.upload_file(
                local_path=local_path,
                relative_path=relative_path,
                parent_version=parent_version,
            )

            # Update local state
            if local_file:
                self._state.mark_synced(
                    relative_path,
                    server_file_id=result.server_file_id,
                    server_version=result.server_version,
                    chunk_hashes=result.chunk_hashes,
                )
            else:
                self._state.add_file(
                    relative_path,
                    local_mtime=local_path.stat().st_mtime,
                    local_size=result.size,
                    local_hash=result.content_hash,
                    status=FileStatus.SYNCED,
                )
                self._state.mark_synced(
                    relative_path,
                    server_file_id=result.server_file_id,
                    server_version=result.server_version,
                    chunk_hashes=result.chunk_hashes,
                )

            return result

        except ConflictError:
            # Intelligent conflict detection
            return self._handle_conflict(relative_path, local_path, server_file)

    def _handle_conflict(
        self,
        relative_path: str,
        local_path: Path,
        server_file: ServerFile | None,
    ) -> UploadResult | None:
        """Handle a conflict with intelligent detection.

        Checks if it's a real conflict or a false positive:
        - Same hash on both sides → auto-resolve (no real conflict)
        - Different content → create conflict copy

        Args:
            relative_path: Relative path of the file.
            local_path: Absolute path to local file.
            server_file: Server file metadata (may be None).

        Returns:
            UploadResult if auto-resolved, None if real conflict.
        """
        # Calculate local file hash
        local_hash = compute_file_hash(local_path)

        # Check if server has the same content (false conflict)
        if server_file and server_file.content_hash == local_hash:
            logger.info(
                f"False conflict for {relative_path}: same content on both sides, auto-resolving"
            )
            # Just update local state to match server
            self._state.mark_synced(
                relative_path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(relative_path),
            )
            self._state.update_file(
                relative_path,
                local_mtime=local_path.stat().st_mtime,
                local_size=local_path.stat().st_size,
                local_hash=local_hash,
            )
            # Return a synthetic result indicating success
            return UploadResult(
                path=relative_path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(relative_path),
                size=server_file.size,
                content_hash=server_file.content_hash,
            )

        # Real conflict - create conflict copy
        logger.warning(f"Real conflict detected for {relative_path}")
        conflict_path = generate_conflict_filename(local_path, self._machine_name)

        # Rename local file to conflict copy
        try:
            local_path.rename(conflict_path)
            logger.info(f"Created conflict copy: {conflict_path.name}")
        except OSError as e:
            logger.error(f"Failed to create conflict copy: {e}")
            self._state.mark_conflict(relative_path)
            return None

        # Download server version to original path
        if server_file:
            try:
                self._downloader.download_file(server_file, local_path)
                # Update state to match server
                self._state.mark_synced(
                    relative_path,
                    server_file_id=server_file.id,
                    server_version=server_file.version,
                    chunk_hashes=self._client.get_file_chunks(relative_path),
                )
            except Exception as e:
                logger.error(f"Failed to download server version: {e}")
                # Restore local file
                conflict_path.rename(local_path)
                self._state.mark_conflict(relative_path)
                return None

        # Notify about conflict
        conflict_info = ConflictInfo(
            original_path=relative_path,
            conflict_path=str(conflict_path.relative_to(self._base_path)),
            local_hash=local_hash,
            server_hash=server_file.content_hash if server_file else "",
            machine_name=self._machine_name,
            timestamp=datetime.now().isoformat(),
        )

        if self._conflict_callback:
            self._conflict_callback(conflict_info)

        self._state.mark_conflict(relative_path)
        return None

    def pull_file(self, server_file: ServerFile) -> DownloadResult:
        """Pull a single file from the server.

        Args:
            server_file: File metadata from server.

        Returns:
            DownloadResult with local metadata.
        """
        local_path = self._base_path / server_file.path

        result = self._downloader.download_file(
            server_file=server_file,
            local_path=local_path,
        )

        # Update local state
        local_file = self._state.get_file(server_file.path)
        if local_file:
            self._state.mark_synced(
                server_file.path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(server_file.path),
            )
        else:
            self._state.add_file(
                server_file.path,
                local_mtime=local_path.stat().st_mtime,
                local_size=server_file.size,
                local_hash=server_file.content_hash,
                status=FileStatus.SYNCED,
            )
            self._state.mark_synced(
                server_file.path,
                server_file_id=server_file.id,
                server_version=server_file.version,
                chunk_hashes=self._client.get_file_chunks(server_file.path),
            )

        return result

    def _scan_local_changes(self) -> None:
        """Scan local folder for new, modified, or deleted files.

        Walks the sync folder and compares with the state database to find:
        - New files (not in state DB)
        - Modified files (different mtime or size)
        - Deleted files (in state DB but not on disk)
        """
        from syncagent.client.sync.watcher import IgnorePatterns

        # Use the same ignore patterns as the watcher
        ignore = IgnorePatterns()
        syncignore_path = self._base_path / ".syncignore"
        ignore.load_from_file(syncignore_path)

        # Track files found on disk
        found_paths: set[str] = set()

        # Note: os.walk with followlinks=False (default) doesn't follow symlinks to directories
        for root_str, dirs, files in os.walk(self._base_path):
            root = Path(root_str)

            # Filter out ignored directories (including symlinks - SC-22)
            dirs[:] = [
                d for d in dirs
                if not ignore.should_ignore(root / d, self._base_path)
            ]

            for filename in files:
                file_path = root / filename

                # Skip symlinks (SC-22) and ignored patterns
                if file_path.is_symlink() or ignore.should_ignore(file_path, self._base_path):
                    continue

                relative_path = str(file_path.relative_to(self._base_path))
                # Normalize path separators
                relative_path = relative_path.replace("\\", "/")
                found_paths.add(relative_path)

                local_file = self._state.get_file(relative_path)
                stat = file_path.stat()

                if local_file is None:
                    # New file - add to state
                    logger.debug(f"Found new local file: {relative_path}")
                    self._state.add_file(
                        relative_path,
                        local_mtime=stat.st_mtime,
                        local_size=stat.st_size,
                        local_hash="",  # Will be computed on upload
                        status=FileStatus.NEW,
                    )
                elif local_file.status == FileStatus.SYNCED:
                    # Check if modified since last sync
                    local_mtime = local_file.local_mtime or 0.0
                    if (
                        stat.st_mtime > local_mtime
                        or stat.st_size != local_file.local_size
                    ):
                        logger.debug(f"Found modified local file: {relative_path}")
                        self._state.mark_modified(relative_path)

        # Check for deleted files (in state DB but not on disk)
        synced_files = self._state.list_files(status=FileStatus.SYNCED)
        for local_file in synced_files:
            if local_file.path not in found_paths:
                # File was deleted locally
                logger.debug(f"Found deleted local file: {local_file.path}")
                self._state.mark_deleted(local_file.path)

    def _push_changes(self) -> dict[str, list[str]]:
        """Push local changes to server.

        Returns:
            Dict with uploaded, deleted, conflicts, and errors lists.
        """
        uploaded: list[str] = []
        deleted: list[str] = []
        conflicts: list[str] = []
        errors: list[str] = []

        # Get files that need uploading
        pending = self._state.get_pending_uploads()
        modified = self._state.list_files(status=FileStatus.MODIFIED)
        new_files = self._state.list_files(status=FileStatus.NEW)

        paths_to_push = set()
        for p in pending:
            paths_to_push.add(p.path)
        for f in modified:
            paths_to_push.add(f.path)
        for f in new_files:
            paths_to_push.add(f.path)

        for path in paths_to_push:
            try:
                result = self.push_file(path)
                if result:
                    uploaded.append(path)
                    self._state.remove_pending_upload(path)
                else:
                    conflicts.append(path)
            except Exception as e:
                logger.error(f"Failed to push {path}: {e}")
                errors.append(f"{path}: {e}")
                self._state.mark_upload_attempt(path, error=str(e))

        # Process deletions
        deleted_files = self._state.list_files(status=FileStatus.DELETED)
        for local_file in deleted_files:
            try:
                self._client.delete_file(local_file.path)
                self._state.remove_file(local_file.path)
                deleted.append(local_file.path)
                logger.info(f"Deleted {local_file.path} from server")
            except NotFoundError:
                # File already deleted on server, just clean up local state
                self._state.remove_file(local_file.path)
                deleted.append(local_file.path)
                logger.debug(f"File {local_file.path} already deleted on server")
            except Exception as e:
                logger.error(f"Failed to delete {local_file.path}: {e}")
                errors.append(f"{local_file.path}: {e}")

        return {"uploaded": uploaded, "deleted": deleted, "conflicts": conflicts, "errors": errors}

    def _pull_changes(self) -> dict[str, list[str]]:
        """Pull remote changes from server.

        Returns:
            Dict with downloaded and errors lists.
        """
        downloaded: list[str] = []
        errors: list[str] = []

        # Get all server files
        server_files = self._client.list_files()

        for server_file in server_files:
            local_file = self._state.get_file(server_file.path)

            # Skip if local is already up to date
            if local_file and local_file.server_version == server_file.version:
                continue

            # Skip if local has unsynced changes
            if local_file and local_file.status in (
                FileStatus.MODIFIED,
                FileStatus.NEW,
                FileStatus.CONFLICT,
            ):
                logger.debug(
                    f"Skipping pull for {server_file.path}: local changes pending"
                )
                continue

            try:
                self.pull_file(server_file)
                downloaded.append(server_file.path)
            except Exception as e:
                logger.error(f"Failed to pull {server_file.path}: {e}")
                errors.append(f"{server_file.path}: {e}")

        return {"downloaded": downloaded, "errors": errors}
