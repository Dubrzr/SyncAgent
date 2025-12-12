"""HTTP client for SyncAgent server API.

This module provides:
- SyncClient: HTTP client for communicating with the server
- File metadata operations (list, create, update, delete)
- Chunk upload/download operations
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import httpx

logger = logging.getLogger(__name__)


class APIError(Exception):
    """Base exception for API errors."""

    def __init__(self, message: str, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class AuthenticationError(APIError):
    """Authentication failed."""


class ConflictError(APIError):
    """Version conflict detected."""


class NotFoundError(APIError):
    """Resource not found."""


@dataclass
class ServerFile:
    """File metadata from server."""

    id: int
    path: str
    size: int
    content_hash: str
    version: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerFile:
        """Create from API response dictionary."""
        return cls(
            id=data["id"],
            path=data["path"],
            size=data["size"],
            content_hash=data["content_hash"],
            version=data["version"],
            created_at=datetime.fromisoformat(data["created_at"]),
            updated_at=datetime.fromisoformat(data["updated_at"]),
            deleted_at=(
                datetime.fromisoformat(data["deleted_at"])
                if data.get("deleted_at")
                else None
            ),
        )


@dataclass
class ServerMachine:
    """Machine info from server."""

    id: int
    name: str
    platform: str
    created_at: datetime
    last_seen: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerMachine:
        """Create from API response dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            platform=data["platform"],
            created_at=datetime.fromisoformat(data["created_at"]),
            last_seen=datetime.fromisoformat(data["last_seen"]),
        )


@dataclass
class ServerChange:
    """Change log entry from server (for incremental sync)."""

    id: int
    file_path: str
    action: str  # CREATED, UPDATED, DELETED
    version: int
    machine_id: int
    timestamp: datetime

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ServerChange:
        """Create from API response dictionary."""
        return cls(
            id=data["id"],
            file_path=data["file_path"],
            action=data["action"],
            version=data["version"],
            machine_id=data["machine_id"],
            timestamp=datetime.fromisoformat(data["timestamp"]),
        )


@dataclass
class ChangesResult:
    """Result of get_changes API call."""

    changes: list[ServerChange]
    has_more: bool
    latest_timestamp: datetime | None


class SyncClient:
    """HTTP client for SyncAgent server API."""

    def __init__(
        self,
        server_url: str,
        token: str,
        timeout: float = 30.0,
    ) -> None:
        """Initialize the sync client.

        Args:
            server_url: Base URL of the server.
            token: Authentication token.
            timeout: Request timeout in seconds.
        """
        self._server_url = server_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._client = httpx.Client(
            base_url=self._server_url,
            timeout=timeout,
            headers={"Authorization": f"Bearer {token}"},
        )

    def close(self) -> None:
        """Close the HTTP client."""
        self._client.close()

    def __enter__(self) -> SyncClient:
        """Context manager entry."""
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.close()

    def _handle_response(self, response: httpx.Response) -> httpx.Response:
        """Handle API response and raise appropriate exceptions."""
        if response.status_code == 401:
            raise AuthenticationError("Invalid or expired token", 401)
        if response.status_code == 404:
            raise NotFoundError("Resource not found", 404)
        if response.status_code == 409:
            detail = response.json().get("detail", "Conflict")
            raise ConflictError(detail, 409)
        if response.status_code >= 400:
            detail = response.json().get("detail", "Unknown error")
            raise APIError(detail, response.status_code)
        return response

    # === Health check ===

    def health_check(self) -> bool:
        """Check if the server is healthy.

        Returns:
            True if server is healthy.
        """
        try:
            response = self._client.get("/health")
            return response.status_code == 200
        except httpx.RequestError:
            return False

    # === Machine operations ===

    def list_machines(self) -> list[ServerMachine]:
        """List all registered machines.

        Returns:
            List of machines.
        """
        response = self._handle_response(self._client.get("/api/machines"))
        return [ServerMachine.from_dict(m) for m in response.json()]

    # === File operations ===

    def list_files(self, prefix: str | None = None) -> list[ServerFile]:
        """List all files on the server.

        Args:
            prefix: Optional path prefix filter.

        Returns:
            List of file metadata.
        """
        params = {}
        if prefix:
            params["prefix"] = prefix
        response = self._handle_response(
            self._client.get("/api/files", params=params)
        )
        return [ServerFile.from_dict(f) for f in response.json()]

    def get_file(self, path: str) -> ServerFile:
        """Get file metadata by path.

        Args:
            path: File path.

        Returns:
            File metadata.

        Raises:
            NotFoundError: If file not found.
        """
        response = self._handle_response(
            self._client.get(f"/api/files/{path}")
        )
        return ServerFile.from_dict(response.json())

    def create_file(
        self,
        path: str,
        size: int,
        content_hash: str,
        chunks: list[str],
    ) -> ServerFile:
        """Create a new file on the server.

        Args:
            path: File path.
            size: File size in bytes.
            content_hash: SHA-256 hash of the file content.
            chunks: List of chunk hashes.

        Returns:
            Created file metadata.
        """
        response = self._handle_response(
            self._client.post(
                "/api/files",
                json={
                    "path": path,
                    "size": size,
                    "content_hash": content_hash,
                    "chunks": chunks,
                },
            )
        )
        return ServerFile.from_dict(response.json())

    def update_file(
        self,
        path: str,
        size: int,
        content_hash: str,
        parent_version: int,
        chunks: list[str],
    ) -> ServerFile:
        """Update a file on the server.

        Args:
            path: File path.
            size: New file size.
            content_hash: New content hash.
            parent_version: Expected current version (for conflict detection).
            chunks: New list of chunk hashes.

        Returns:
            Updated file metadata.

        Raises:
            ConflictError: If version conflict detected.
            NotFoundError: If file not found.
        """
        response = self._handle_response(
            self._client.put(
                f"/api/files/{path}",
                json={
                    "size": size,
                    "content_hash": content_hash,
                    "parent_version": parent_version,
                    "chunks": chunks,
                },
            )
        )
        return ServerFile.from_dict(response.json())

    def delete_file(self, path: str) -> None:
        """Delete a file (soft delete to trash).

        Args:
            path: File path to delete.
        """
        self._handle_response(self._client.delete(f"/api/files/{path}"))

    def get_file_chunks(self, path: str) -> list[str]:
        """Get chunk hashes for a file.

        Args:
            path: File path.

        Returns:
            List of chunk hashes.
        """
        response = self._handle_response(
            self._client.get(f"/api/chunks/{path}")
        )
        result: list[str] = response.json()
        return result

    # === Chunk storage operations ===

    def upload_chunk(self, chunk_hash: str, data: bytes) -> None:
        """Upload an encrypted chunk.

        Args:
            chunk_hash: SHA-256 hash of the chunk (before encryption).
            data: Encrypted chunk data.
        """
        self._handle_response(
            self._client.put(
                f"/api/storage/chunks/{chunk_hash}",
                content=data,
                headers={"Content-Type": "application/octet-stream"},
            )
        )

    def download_chunk(self, chunk_hash: str) -> bytes:
        """Download an encrypted chunk.

        Args:
            chunk_hash: Chunk hash.

        Returns:
            Encrypted chunk data.

        Raises:
            NotFoundError: If chunk not found.
        """
        response = self._handle_response(
            self._client.get(f"/api/storage/chunks/{chunk_hash}")
        )
        return response.content

    def chunk_exists(self, chunk_hash: str) -> bool:
        """Check if a chunk exists on the server.

        Args:
            chunk_hash: Chunk hash.

        Returns:
            True if chunk exists.
        """
        response = self._client.head(f"/api/storage/chunks/{chunk_hash}")
        return response.status_code == 200

    def delete_chunk(self, chunk_hash: str) -> bool:
        """Delete a chunk from storage.

        Args:
            chunk_hash: Chunk hash.

        Returns:
            True if chunk was deleted.
        """
        response = self._client.delete(f"/api/storage/chunks/{chunk_hash}")
        return response.status_code == 204

    # === Trash operations ===

    def list_trash(self) -> list[ServerFile]:
        """List files in trash.

        Returns:
            List of deleted files.
        """
        response = self._handle_response(self._client.get("/api/trash"))
        return [ServerFile.from_dict(f) for f in response.json()]

    def restore_file(self, path: str) -> ServerFile:
        """Restore a file from trash.

        Args:
            path: File path to restore.

        Returns:
            Restored file metadata.
        """
        response = self._handle_response(
            self._client.post(f"/api/trash/{path}/restore")
        )
        return ServerFile.from_dict(response.json())

    # === Change log operations (incremental sync) ===

    def get_changes(
        self,
        since: datetime,
        limit: int = 1000,
    ) -> ChangesResult:
        """Get changes since a given timestamp.

        This is used for incremental sync instead of list_files().
        Clients should store the latest_timestamp from the response
        and use it as 'since' for subsequent calls.

        Args:
            since: Get changes after this timestamp.
            limit: Maximum number of changes to return.

        Returns:
            ChangesResult with list of changes and metadata.
        """
        response = self._handle_response(
            self._client.get(
                "/api/changes",
                params={"since": since.isoformat(), "limit": str(limit)},
            )
        )
        data = response.json()
        return ChangesResult(
            changes=[ServerChange.from_dict(c) for c in data["changes"]],
            has_more=data["has_more"],
            latest_timestamp=(
                datetime.fromisoformat(data["latest_timestamp"])
                if data["latest_timestamp"]
                else None
            ),
        )

    def get_latest_change_timestamp(self) -> datetime | None:
        """Get the timestamp of the most recent change.

        This can be used to quickly check if there are any changes
        without fetching all the details.

        Returns:
            Timestamp of most recent change, or None if no changes exist.
        """
        response = self._handle_response(
            self._client.get("/api/changes/latest")
        )
        data = response.json()
        if data["latest_timestamp"]:
            return datetime.fromisoformat(data["latest_timestamp"])
        return None
