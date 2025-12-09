"""Content-Defined Chunking (CDC) for SyncAgent.

This module provides CDC using FastCDC algorithm for:
- Efficient delta synchronization
- Stable chunk boundaries (insertions don't affect distant chunks)
- Configurable chunk sizes (min 1MB, avg 4MB, max 8MB)
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from fastcdc import fastcdc

# Chunk size configuration (in bytes)
MIN_CHUNK_SIZE = 1 * 1024 * 1024   # 1 MB
AVG_CHUNK_SIZE = 4 * 1024 * 1024   # 4 MB
MAX_CHUNK_SIZE = 8 * 1024 * 1024   # 8 MB


@dataclass
class Chunk:
    """Represents a chunk of data with metadata."""

    index: int
    offset: int
    data: bytes
    hash: str

    @property
    def size(self) -> int:
        """Return the size of this chunk in bytes."""
        return len(self.data)


def get_chunk_hash(data: bytes) -> str:
    """Compute SHA-256 hash of data.

    Args:
        data: Raw bytes to hash.

    Returns:
        Hex-encoded SHA-256 hash string (64 characters).
    """
    return hashlib.sha256(data).hexdigest()


def chunk_bytes(data: bytes) -> Iterator[Chunk]:
    """Split data into content-defined chunks.

    Uses FastCDC algorithm to find chunk boundaries based on
    content, ensuring that insertions only affect nearby chunks.

    Args:
        data: Raw bytes to chunk.

    Yields:
        Chunk objects with index, offset, data, and hash.
    """
    if not data:
        return

    # FastCDC expects data and returns chunk boundaries
    chunks = fastcdc(
        data,
        min_size=MIN_CHUNK_SIZE,
        avg_size=AVG_CHUNK_SIZE,
        max_size=MAX_CHUNK_SIZE,
    )

    for index, cdc_chunk in enumerate(chunks):
        chunk_data = data[cdc_chunk.offset : cdc_chunk.offset + cdc_chunk.length]
        yield Chunk(
            index=index,
            offset=cdc_chunk.offset,
            data=chunk_data,
            hash=get_chunk_hash(chunk_data),
        )


def chunk_file(path: Path) -> Iterator[Chunk]:
    """Split a file into content-defined chunks.

    Reads the entire file into memory. For very large files,
    consider using a streaming approach.

    Args:
        path: Path to the file to chunk.

    Yields:
        Chunk objects with index, offset, data, and hash.

    Raises:
        FileNotFoundError: If the file does not exist.
    """
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(f"File not found: {path}")

    data = path.read_bytes()
    yield from chunk_bytes(data)
