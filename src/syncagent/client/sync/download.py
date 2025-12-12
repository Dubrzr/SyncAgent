"""File download with decryption and assembly.

This module provides:
- FileDownloader: Handles file download with atomic writes
"""

from __future__ import annotations

import contextlib
import logging
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.api import NotFoundError
from syncagent.client.sync.retry import DEFAULT_MAX_RETRIES, retry_with_network_wait
from syncagent.client.sync.types import (
    DownloadError,
    DownloadResult,
    ProgressCallback,
    SyncProgress,
)
from syncagent.core.crypto import decrypt_chunk

if TYPE_CHECKING:
    from syncagent.client.api import ServerFile, SyncClient

logger = logging.getLogger(__name__)


class FileDownloader:
    """Handles file download with decryption and assembly."""

    def __init__(
        self,
        client: SyncClient,
        encryption_key: bytes,
        progress_callback: ProgressCallback | None = None,
        max_retries: int = DEFAULT_MAX_RETRIES,
    ) -> None:
        """Initialize the downloader.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for decryption.
            progress_callback: Optional callback for progress updates.
            max_retries: Maximum retry attempts for chunk downloads.
        """
        self._client = client
        self._key = encryption_key
        self._progress_callback = progress_callback
        self._max_retries = max_retries

    def download_file(
        self,
        server_file: ServerFile,
        local_path: Path,
    ) -> DownloadResult:
        """Download a file from the server with atomic write.

        Uses a temporary file (.tmp) during download, then atomically
        renames to the target path on success. This ensures no partial
        files are left on disk if download is interrupted.

        Args:
            server_file: File metadata from server.
            local_path: Absolute path where to save the file.

        Returns:
            DownloadResult with local metadata.

        Raises:
            DownloadError: If download fails after all retries.
        """
        logger.info(f"Downloading {server_file.path}")

        # Get chunk hashes
        chunk_hashes = self._client.get_file_chunks(server_file.path)

        # Ensure parent directory exists
        local_path.parent.mkdir(parents=True, exist_ok=True)

        # Use temporary file for atomic write
        tmp_path = local_path.with_suffix(local_path.suffix + ".tmp")

        try:
            # Download and assemble chunks to temp file
            bytes_transferred = 0
            with open(tmp_path, "wb") as f:
                for i, chunk_hash in enumerate(chunk_hashes):
                    try:
                        # Download chunk with retry
                        encrypted = self._download_chunk_with_retry(chunk_hash)
                        decrypted = decrypt_chunk(encrypted, self._key)
                        f.write(decrypted)
                        bytes_transferred += len(decrypted)
                        logger.debug(
                            f"Downloaded chunk {i + 1}/{len(chunk_hashes)}: "
                            f"{chunk_hash[:8]}..."
                        )

                        # Report progress
                        if self._progress_callback:
                            self._progress_callback(SyncProgress(
                                file_path=server_file.path,
                                file_size=server_file.size,
                                current_chunk=i + 1,
                                total_chunks=len(chunk_hashes),
                                bytes_transferred=bytes_transferred,
                                operation="download",
                            ))
                    except NotFoundError as e:
                        raise DownloadError(
                            f"Chunk {chunk_hash} not found for {server_file.path}"
                        ) from e
                    except Exception as e:
                        raise DownloadError(
                            f"Failed to download chunk {chunk_hash}: {e}"
                        ) from e

            # Atomic rename: tmp -> final path
            # On Windows, need to remove existing file first
            if local_path.exists():
                local_path.unlink()
            tmp_path.rename(local_path)

            logger.info(
                f"Downloaded {server_file.path}: {len(chunk_hashes)} chunks, "
                f"version {server_file.version}"
            )

            return DownloadResult(
                path=server_file.path,
                local_path=local_path,
                size=server_file.size,
                version=server_file.version,
            )

        except Exception:
            # Clean up temp file on failure
            if tmp_path.exists():
                with contextlib.suppress(OSError):
                    tmp_path.unlink()
            raise

    def _download_chunk_with_retry(self, chunk_hash: str) -> bytes:
        """Download a chunk with network-aware retry.

        Uses retry_with_network_wait which waits indefinitely for network
        to be restored on connectivity errors, rather than failing.

        Args:
            chunk_hash: Hash of the chunk to download.

        Returns:
            Encrypted chunk data.
        """
        result: bytes = retry_with_network_wait(
            func=lambda: self._client.download_chunk(chunk_hash),
            client=self._client,
            max_retries=self._max_retries,
            retryable_exceptions=(Exception,),  # Retry all, network handled separately
        )
        return result
