"""Version tracking and comparison.

Tracks:
- server_version: Version counter from server (increments on each change)
- local state: mtime/size when we last synced

Version rules:
- New file: version = None (will be assigned by server)
- Update: must provide parent_version (optimistic locking)
- Conflict: server_version != expected parent_version
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass
class VersionInfo:
    """Version information for a file."""

    server_version: int | None  # None = new file
    local_mtime: float | None  # When we last synced
    local_size: int | None  # Size when we last synced
    chunk_hashes: list[str] | None = None  # Content hashes


class VersionStore(Protocol):
    """Protocol for storing/retrieving version info."""

    def get_version_info(self, path: str) -> VersionInfo | None:
        """Get version info for a path."""
        ...

    def set_version_info(self, path: str, info: VersionInfo) -> None:
        """Store version info for a path."""
        ...

    def delete_version_info(self, path: str) -> None:
        """Remove version info for a path."""
        ...


class VersionChecker:
    """Checks version consistency."""

    def __init__(self, store: VersionStore) -> None:
        self._store = store

    def is_locally_modified(
        self, path: str, current_mtime: float, current_size: int
    ) -> bool:
        """Check if local file was modified since last sync."""
        info = self._store.get_version_info(path)
        if info is None:
            return True  # New file = "modified"

        return current_mtime > (info.local_mtime or 0) or current_size != info.local_size

    def get_parent_version(self, path: str) -> int | None:
        """Get version to use as parent for update."""
        info = self._store.get_version_info(path)
        return info.server_version if info else None

    def needs_download(self, path: str, server_version: int) -> bool:
        """Check if server version is newer than what we have."""
        info = self._store.get_version_info(path)
        if info is None:
            return True  # Don't have it

        return server_version > (info.server_version or 0)

    def is_tracked(self, path: str) -> bool:
        """Check if a path is tracked in the version store."""
        return self._store.get_version_info(path) is not None

    def get_tracked_state(self, path: str) -> tuple[float | None, int | None]:
        """Get the tracked mtime and size for a path.

        Returns:
            (mtime, size) tuple, or (None, None) if not tracked
        """
        info = self._store.get_version_info(path)
        if info is None:
            return None, None
        return info.local_mtime, info.local_size


class VersionUpdater:
    """Updates version store after sync operations."""

    def __init__(self, store: VersionStore) -> None:
        self._store = store

    def mark_synced(
        self,
        path: str,
        server_version: int,
        local_mtime: float,
        local_size: int,
        chunk_hashes: list[str] | None = None,
    ) -> None:
        """Record successful sync."""
        self._store.set_version_info(
            path,
            VersionInfo(
                server_version=server_version,
                local_mtime=local_mtime,
                local_size=local_size,
                chunk_hashes=chunk_hashes,
            ),
        )

    def mark_deleted(self, path: str) -> None:
        """Record file deletion."""
        self._store.delete_version_info(path)
