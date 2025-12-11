"""Block storage abstraction for encrypted chunks.

This module provides:
- Abstract interface for chunk storage
- LocalFSStorage for development/testing
- S3Storage for production (OVH, AWS, MinIO)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from typing import Any


class ChunkNotFoundError(Exception):
    """Raised when a chunk is not found in storage."""


class ChunkStorage(ABC):
    """Abstract interface for encrypted chunk storage."""

    @property
    @abstractmethod
    def location(self) -> str:
        """Return a human-readable description of where chunks are stored."""

    @abstractmethod
    def put(self, chunk_hash: str, data: bytes) -> None:
        """Store an encrypted chunk.

        Args:
            chunk_hash: SHA-256 hash of the chunk (before encryption).
            data: Encrypted chunk data.
        """

    @abstractmethod
    def get(self, chunk_hash: str) -> bytes:
        """Retrieve an encrypted chunk.

        Args:
            chunk_hash: SHA-256 hash of the chunk.

        Returns:
            Encrypted chunk data.

        Raises:
            ChunkNotFoundError: If chunk doesn't exist.
        """

    @abstractmethod
    def exists(self, chunk_hash: str) -> bool:
        """Check if a chunk exists in storage.

        Args:
            chunk_hash: SHA-256 hash of the chunk.

        Returns:
            True if chunk exists, False otherwise.
        """

    @abstractmethod
    def delete(self, chunk_hash: str) -> bool:
        """Delete a chunk from storage.

        Args:
            chunk_hash: SHA-256 hash of the chunk.

        Returns:
            True if chunk was deleted, False if it didn't exist.
        """


class LocalFSStorage(ChunkStorage):
    """Local filesystem storage for development and testing.

    Chunks are stored in subdirectories based on hash prefix
    to avoid too many files in a single directory.
    """

    def __init__(self, base_path: Path | str) -> None:
        """Initialize local storage.

        Args:
            base_path: Base directory for chunk storage.
        """
        self._base_path = Path(base_path).resolve()
        self._base_path.mkdir(parents=True, exist_ok=True)

    @property
    def location(self) -> str:
        """Return the local storage path."""
        return f"Local filesystem: {self._base_path}"

    def _chunk_path(self, chunk_hash: str) -> Path:
        """Get the file path for a chunk.

        Uses first 2 characters of hash as subdirectory prefix.
        """
        prefix = chunk_hash[:2]
        return self._base_path / prefix / f"{chunk_hash}.enc"

    def put(self, chunk_hash: str, data: bytes) -> None:
        """Store an encrypted chunk."""
        path = self._chunk_path(chunk_hash)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)

    def get(self, chunk_hash: str) -> bytes:
        """Retrieve an encrypted chunk."""
        path = self._chunk_path(chunk_hash)
        if not path.exists():
            raise ChunkNotFoundError(f"Chunk not found: {chunk_hash}")
        return path.read_bytes()

    def exists(self, chunk_hash: str) -> bool:
        """Check if a chunk exists."""
        return self._chunk_path(chunk_hash).exists()

    def delete(self, chunk_hash: str) -> bool:
        """Delete a chunk."""
        path = self._chunk_path(chunk_hash)
        if path.exists():
            path.unlink()
            return True
        return False


class S3Storage(ChunkStorage):
    """S3-compatible storage for production (OVH, AWS, MinIO, etc.)."""

    def __init__(
        self,
        bucket: str,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        region: str = "us-east-1",
    ) -> None:
        """Initialize S3 storage.

        Args:
            bucket: S3 bucket name.
            endpoint_url: Custom endpoint URL (for OVH, MinIO, etc.).
            access_key: AWS access key ID.
            secret_key: AWS secret access key.
            region: AWS region (default: us-east-1).
        """
        import boto3

        self._bucket = bucket
        self._endpoint_url = endpoint_url
        self._client: Any = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            region_name=region,
        )

    @property
    def location(self) -> str:
        """Return the S3 bucket location."""
        if self._endpoint_url:
            return f"S3: {self._endpoint_url}/{self._bucket}"
        return f"S3: s3://{self._bucket}"

    def _key(self, chunk_hash: str) -> str:
        """Get the S3 key for a chunk."""
        return f"chunks/{chunk_hash[:2]}/{chunk_hash}.enc"

    def put(self, chunk_hash: str, data: bytes) -> None:
        """Store an encrypted chunk."""
        self._client.put_object(
            Bucket=self._bucket,
            Key=self._key(chunk_hash),
            Body=data,
        )

    def get(self, chunk_hash: str) -> bytes:
        """Retrieve an encrypted chunk."""
        from botocore.exceptions import ClientError

        try:
            response = self._client.get_object(
                Bucket=self._bucket,
                Key=self._key(chunk_hash),
            )
            body: bytes = response["Body"].read()
            return body
        except ClientError as e:
            if e.response["Error"]["Code"] == "NoSuchKey":
                raise ChunkNotFoundError(f"Chunk not found: {chunk_hash}") from e
            raise

    def exists(self, chunk_hash: str) -> bool:
        """Check if a chunk exists."""
        from botocore.exceptions import ClientError

        try:
            self._client.head_object(
                Bucket=self._bucket,
                Key=self._key(chunk_hash),
            )
            return True
        except ClientError:
            return False

    def delete(self, chunk_hash: str) -> bool:
        """Delete a chunk."""
        if not self.exists(chunk_hash):
            return False
        self._client.delete_object(
            Bucket=self._bucket,
            Key=self._key(chunk_hash),
        )
        return True


def create_storage(config: dict[str, str | None]) -> ChunkStorage:
    """Factory function to create storage from configuration.

    Args:
        config: Storage configuration dict with keys:
            - type: "local" or "s3"
            - For local: local_path
            - For S3: bucket, endpoint_url, access_key, secret_key, region

    Returns:
        Configured ChunkStorage instance.

    Raises:
        ValueError: If storage type is unknown.
    """
    storage_type = config.get("type", "local")

    if storage_type == "local":
        local_path = config.get("local_path", "./chunks")
        if local_path is None:
            local_path = "./chunks"
        return LocalFSStorage(local_path)

    if storage_type == "s3":
        bucket = config.get("bucket")
        if not bucket:
            raise ValueError("S3 storage requires 'bucket' configuration")
        return S3Storage(
            bucket=bucket,
            endpoint_url=config.get("endpoint_url"),
            access_key=config.get("access_key"),
            secret_key=config.get("secret_key"),
            region=config.get("region") or "us-east-1",
        )

    raise ValueError(f"Unknown storage type: {storage_type}")
