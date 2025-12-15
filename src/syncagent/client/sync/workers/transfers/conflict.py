from __future__ import annotations

import logging
import socket
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from syncagent.client.api import HTTPClient
from syncagent.client.state import LocalSyncState

# Re-export from domain for backwards compatibility
from syncagent.client.sync.domain.conflicts import (
    ConflictOutcome,
    RaceConditionError,
)

__all__ = [
    "ConflictOutcome",
    "RaceConditionError",
    "ConflictResolution",
    "resolve_upload_conflict",
    "safe_rename_for_conflict",
]

logger = logging.getLogger(__name__)


@dataclass
class ConflictResolution:
    """Result of conflict resolution.

    Attributes:
        outcome: What happened during resolution.
        conflict_path: Path to the conflict file (if created).
        server_version: Server version after resolution.
    """

    outcome: ConflictOutcome
    conflict_path: Path | None = None
    server_version: int | None = None


def resolve_upload_conflict(
    client: HTTPClient,
    encryption_key: bytes,
    local_path: Path,
    relative_path: str,
    state: LocalSyncState,
    base_path: Path,
) -> ConflictResolution:
    """Resolve a conflict detected during upload.

    This function implements the "Server Wins + Local Preserved" strategy:
    1. Fetch server file info to get content hash
    2. Compare with local hash - if identical, not a real conflict
    3. If different: rename local to .conflict-*, download server version
    4. Update state DB and notify user

    Args:
        client: HTTP client for server communication.
        encryption_key: Encryption key for downloading server file.
        local_path: Absolute path to the local file.
        relative_path: Relative path (used for state DB and API).
        state: Local sync state database.
        base_path: Base directory for sync.

    Returns:
        ConflictResolution with outcome and details.
    """
    from syncagent.client.notifications import notify_conflict
    from syncagent.client.state import FileStatus
    from syncagent.client.sync.workers.transfers import FileDownloader
    from syncagent.core.crypto import compute_file_hash

    # 1. Get server file info
    server_file = client.get_file_metadata(relative_path)
    server_hash = server_file.content_hash
    server_version = server_file.version

    # 2. Compare hashes
    local_hash = compute_file_hash(local_path)

    if local_hash == server_hash:
        # Same content - not a real conflict!
        logger.info(f"False conflict for {relative_path}: hashes match, marking as synced")
        local_stat = local_path.stat()
        state.mark_synced(
            relative_path,
            server_file_id=server_file.id,
            server_version=server_version,
            chunk_hashes=[],  # Not needed for conflict resolution
            local_mtime=local_stat.st_mtime,
            local_size=local_stat.st_size,
        )
        return ConflictResolution(
            outcome=ConflictOutcome.ALREADY_SYNCED,
            server_version=server_version,
        )

    # 3. Real conflict - rename local file
    logger.warning(f"Real conflict for {relative_path}: local hash {local_hash[:8]}... != server hash {server_hash[:8]}...")

    try:
        conflict_path = safe_rename_for_conflict(local_path)
    except RaceConditionError:
        logger.warning(f"Race condition during conflict resolution for {relative_path}")
        return ConflictResolution(outcome=ConflictOutcome.RETRY_NEEDED)

    # 4. Download server version
    downloader = FileDownloader(client, encryption_key)
    downloader.download_file(server_file, local_path)

    # 5. Update state DB
    # Mark the original path as synced with server version
    downloaded_stat = local_path.stat()
    state.mark_synced(
        relative_path,
        server_file_id=server_file.id,
        server_version=server_version,
        chunk_hashes=[],  # Not needed for conflict resolution
        local_mtime=downloaded_stat.st_mtime,
        local_size=downloaded_stat.st_size,
    )

    # Add the conflict file to state as NEW (will be uploaded on next sync)
    conflict_relative = str(conflict_path.relative_to(base_path)).replace("\\", "/")
    state.add_file(
        conflict_relative,
        local_mtime=conflict_path.stat().st_mtime,
        local_size=conflict_path.stat().st_size,
        local_hash=local_hash,
        status=FileStatus.NEW,
    )

    # 6. Notify user
    notify_conflict(Path(relative_path).name, "another device")

    logger.info(f"Conflict resolved for {relative_path}: local saved as {conflict_path.name}")

    return ConflictResolution(
        outcome=ConflictOutcome.RESOLVED,
        conflict_path=conflict_path,
        server_version=server_version,
    )


def check_download_conflict(
    local_path: Path,
    relative_path: str,
    state: LocalSyncState,
    base_path: Path,
) -> ConflictResolution:
    """Check if local file was modified before a download overwrites it.

    This detects the race condition where:
    1. Scan detected only remote changes → scheduled download
    2. User modified local file after scan
    3. Download would overwrite user's changes

    If conflict detected, renames local file to .conflict-* BEFORE download.

    Args:
        local_path: Absolute path to the local file.
        relative_path: Relative path (used for state DB).
        state: Local sync state database.
        base_path: Base directory for sync.

    Returns:
        ConflictResolution with outcome:
        - ALREADY_SYNCED: No conflict, proceed with download
        - RESOLVED: Local renamed to .conflict-*, proceed with download
        - RETRY_NEEDED: Race condition during rename, retry later
    """
    from syncagent.client.notifications import notify_conflict
    from syncagent.client.state import FileStatus
    from syncagent.core.crypto import compute_file_hash

    # If file doesn't exist locally, no conflict possible
    if not local_path.exists():
        return ConflictResolution(outcome=ConflictOutcome.ALREADY_SYNCED)

    # Get tracked state for this file
    tracked_file = state.get_file(relative_path)

    if tracked_file is None:
        # File exists locally but not tracked - this is a conflict!
        # Local file appeared after scan
        logger.warning(f"Download conflict: untracked local file {relative_path}")
        local_hash = compute_file_hash(local_path)

        try:
            conflict_path = safe_rename_for_conflict(local_path)
        except RaceConditionError:
            return ConflictResolution(outcome=ConflictOutcome.RETRY_NEEDED)

        # Add conflict file to state
        conflict_relative = str(conflict_path.relative_to(base_path)).replace("\\", "/")
        state.add_file(
            conflict_relative,
            local_mtime=conflict_path.stat().st_mtime,
            local_size=conflict_path.stat().st_size,
            local_hash=local_hash,
            status=FileStatus.NEW,
        )

        notify_conflict(Path(relative_path).name, "another device")

        return ConflictResolution(
            outcome=ConflictOutcome.RESOLVED,
            conflict_path=conflict_path,
        )

    # File is tracked - check if modified since last sync
    current_stat = local_path.stat()
    tracked_mtime = tracked_file.local_mtime or 0.0
    tracked_size = tracked_file.local_size or 0

    # Check if file was modified (mtime or size changed)
    if current_stat.st_mtime > tracked_mtime or current_stat.st_size != tracked_size:
        # Local was modified after scan - conflict!
        logger.warning(
            f"Download conflict: {relative_path} modified after scan "
            f"(mtime {tracked_mtime} → {current_stat.st_mtime})"
        )
        local_hash = compute_file_hash(local_path)

        try:
            conflict_path = safe_rename_for_conflict(local_path)
        except RaceConditionError:
            return ConflictResolution(outcome=ConflictOutcome.RETRY_NEEDED)

        # Update state: mark original as needing re-scan, add conflict file
        state.mark_modified(relative_path)

        conflict_relative = str(conflict_path.relative_to(base_path)).replace("\\", "/")
        state.add_file(
            conflict_relative,
            local_mtime=conflict_path.stat().st_mtime,
            local_size=conflict_path.stat().st_size,
            local_hash=local_hash,
            status=FileStatus.NEW,
        )

        notify_conflict(Path(relative_path).name, "another device")

        return ConflictResolution(
            outcome=ConflictOutcome.RESOLVED,
            conflict_path=conflict_path,
        )

    # No modification - safe to overwrite
    return ConflictResolution(outcome=ConflictOutcome.ALREADY_SYNCED)


def safe_rename_for_conflict(local_path: Path, machine_name: str | None = None) -> Path:
    """Rename a local file to .conflict-* with race condition protection.

    This function captures the mtime before renaming, performs the rename,
    then verifies the mtime hasn't changed. If the file was modified during
    the rename operation, it rolls back and raises RaceConditionError.

    Args:
        local_path: Path to the local file to rename.
        machine_name: Optional machine name override.

    Returns:
        Path to the renamed conflict file.

    Raises:
        RaceConditionError: If the file was modified during the rename.
        FileNotFoundError: If the file doesn't exist.
        OSError: If the rename fails.
    """
    # 1. Capture mtime before rename
    mtime_before = local_path.stat().st_mtime

    # 2. Generate conflict filename
    conflict_path = generate_conflict_filename(local_path, machine_name)

    # 3. Ensure conflict path doesn't already exist (very unlikely with ms timestamp)
    if conflict_path.exists():
        # Add extra uniqueness
        import time
        conflict_path = conflict_path.with_stem(
            conflict_path.stem + f"-{int(time.time() * 1000) % 1000:03d}"
        )

    # 4. Rename the file
    logger.debug(f"Renaming {local_path} to {conflict_path}")
    local_path.rename(conflict_path)

    # 5. Verify mtime hasn't changed (check on the renamed file)
    mtime_after = conflict_path.stat().st_mtime

    if mtime_after != mtime_before:
        # File was modified during the rename - roll back!
        logger.warning(f"Race condition detected: {local_path} was modified during rename")
        conflict_path.rename(local_path)
        raise RaceConditionError(f"File {local_path} was modified during conflict resolution")

    logger.info(f"Created conflict file: {conflict_path}")
    return conflict_path


def generate_conflict_filename(original_path: Path, machine_name: str | None = None) -> Path:
    """Generate a conflict filename with timestamp and machine name.

    Format: filename.conflict-YYYYMMDD-HHMMSS-{machine}.ext

    Args:
        original_path: Original file path.
        machine_name: Machine name (defaults to registered name from config).

    Returns:
        Path with conflict naming.
    """
    # Import here to avoid circular imports
    from syncagent.client.cli import sanitize_machine_name

    # get_machine_name() returns already sanitized names, but explicit names need sanitizing
    machine_name = get_machine_name() if machine_name is None else sanitize_machine_name(machine_name)

    now = datetime.now()
    # Include milliseconds for uniqueness when multiple conflicts happen quickly
    timestamp = now.strftime("%Y%m%d-%H%M%S") + f"{now.microsecond // 1000:03d}"
    stem = original_path.stem
    suffix = original_path.suffix

    new_name = f"{stem}.conflict-{timestamp}-{machine_name}{suffix}"
    return original_path.parent / new_name


def get_machine_name() -> str:
    """Get the machine name for conflict file naming.

    Returns the registered machine name from config if available,
    otherwise falls back to the hostname (sanitized).

    Returns:
        Machine name (already safe for filenames if from config).
    """
    # Import here to avoid circular imports
    from syncagent.client.cli import get_registered_machine_name, sanitize_machine_name

    # Try to get registered name from config
    registered_name = get_registered_machine_name()
    if registered_name:
        return registered_name

    # Fallback to hostname (sanitized) if not registered
    return sanitize_machine_name(socket.gethostname())


# Note: RaceConditionError and ConflictOutcome are now imported from domain/conflicts.py
# and re-exported for backwards compatibility
