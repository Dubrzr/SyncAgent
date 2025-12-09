"""Tests for Content-Defined Chunking (CDC) module."""

import hashlib
import os
from pathlib import Path

import pytest

from syncagent.core.chunking import (
    AVG_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    Chunk,
    chunk_bytes,
    chunk_file,
    get_chunk_hash,
)


class TestChunkSizes:
    """Tests for chunk size constraints."""

    def test_chunk_sizes_constants(self) -> None:
        """Verify chunk size constants are correct."""
        assert MIN_CHUNK_SIZE == 1 * 1024 * 1024  # 1 MB
        assert AVG_CHUNK_SIZE == 4 * 1024 * 1024  # 4 MB
        assert MAX_CHUNK_SIZE == 8 * 1024 * 1024  # 8 MB

    def test_chunks_respect_max_size(self) -> None:
        """All chunks should be <= MAX_CHUNK_SIZE."""
        data = os.urandom(20 * 1024 * 1024)  # 20 MB
        chunks = list(chunk_bytes(data))
        for chunk in chunks:
            assert len(chunk.data) <= MAX_CHUNK_SIZE

    def test_chunks_respect_min_size_except_last(self) -> None:
        """All chunks except possibly the last should be >= MIN_CHUNK_SIZE."""
        data = os.urandom(20 * 1024 * 1024)  # 20 MB
        chunks = list(chunk_bytes(data))
        for chunk in chunks[:-1]:  # All except last
            assert len(chunk.data) >= MIN_CHUNK_SIZE


class TestChunkingBasics:
    """Basic chunking functionality tests."""

    def test_empty_data_produces_no_chunks(self) -> None:
        """Empty data should produce no chunks."""
        chunks = list(chunk_bytes(b""))
        assert len(chunks) == 0

    def test_small_data_produces_one_chunk(self) -> None:
        """Data smaller than MIN_CHUNK_SIZE produces one chunk."""
        data = b"small data"
        chunks = list(chunk_bytes(data))
        assert len(chunks) == 1
        assert chunks[0].data == data

    def test_chunk_has_correct_offset(self) -> None:
        """Chunks should have correct offset values."""
        data = os.urandom(10 * 1024 * 1024)  # 10 MB
        chunks = list(chunk_bytes(data))
        current_offset = 0
        for chunk in chunks:
            assert chunk.offset == current_offset
            current_offset += len(chunk.data)

    def test_chunks_concatenate_to_original(self) -> None:
        """Concatenating all chunks should produce original data."""
        data = os.urandom(15 * 1024 * 1024)  # 15 MB
        chunks = list(chunk_bytes(data))
        reconstructed = b"".join(chunk.data for chunk in chunks)
        assert reconstructed == data

    def test_chunk_index_sequential(self) -> None:
        """Chunk indices should be sequential starting from 0."""
        data = os.urandom(10 * 1024 * 1024)
        chunks = list(chunk_bytes(data))
        for i, chunk in enumerate(chunks):
            assert chunk.index == i


class TestChunkHashing:
    """Tests for chunk hash computation."""

    def test_chunk_has_sha256_hash(self) -> None:
        """Each chunk should have a SHA-256 hash."""
        data = os.urandom(5 * 1024 * 1024)
        chunks = list(chunk_bytes(data))
        for chunk in chunks:
            assert len(chunk.hash) == 64  # SHA-256 hex = 64 chars

    def test_chunk_hash_is_correct(self) -> None:
        """Chunk hash should match SHA-256 of chunk data."""
        data = os.urandom(5 * 1024 * 1024)
        chunks = list(chunk_bytes(data))
        for chunk in chunks:
            expected_hash = hashlib.sha256(chunk.data).hexdigest()
            assert chunk.hash == expected_hash

    def test_get_chunk_hash_function(self) -> None:
        """get_chunk_hash should compute correct SHA-256."""
        data = b"test data for hashing"
        expected = hashlib.sha256(data).hexdigest()
        assert get_chunk_hash(data) == expected

    def test_same_content_same_hash(self) -> None:
        """Same content should produce same hash."""
        data = b"repeated content"
        hash1 = get_chunk_hash(data)
        hash2 = get_chunk_hash(data)
        assert hash1 == hash2


class TestCDCStability:
    """Tests for CDC boundary stability."""

    def test_insertion_only_affects_nearby_chunks(self) -> None:
        """Inserting data should only affect chunks near the insertion point."""
        # Create base data
        base = os.urandom(20 * 1024 * 1024)  # 20 MB
        base_chunks = list(chunk_bytes(base))
        base_hashes = {chunk.hash for chunk in base_chunks}

        # Insert data in the middle
        insert_point = len(base) // 2
        inserted = base[:insert_point] + os.urandom(1000) + base[insert_point:]
        inserted_chunks = list(chunk_bytes(inserted))
        inserted_hashes = {chunk.hash for chunk in inserted_chunks}

        # Many chunks should be unchanged (shared hashes)
        shared = base_hashes & inserted_hashes
        # At least half of the original chunks should be preserved
        assert len(shared) >= len(base_chunks) // 2

    def test_append_only_affects_last_chunk(self) -> None:
        """Appending data should not change earlier chunks."""
        base = os.urandom(15 * 1024 * 1024)
        base_chunks = list(chunk_bytes(base))

        # Append data
        appended = base + os.urandom(2 * 1024 * 1024)
        appended_chunks = list(chunk_bytes(appended))

        # All original chunks except possibly the last should be unchanged
        for i in range(len(base_chunks) - 1):
            assert base_chunks[i].hash == appended_chunks[i].hash

    def test_deterministic_chunking(self) -> None:
        """Same data should always produce same chunks."""
        data = os.urandom(10 * 1024 * 1024)
        chunks1 = list(chunk_bytes(data))
        chunks2 = list(chunk_bytes(data))

        assert len(chunks1) == len(chunks2)
        for c1, c2 in zip(chunks1, chunks2, strict=True):
            assert c1.hash == c2.hash
            assert c1.offset == c2.offset
            assert len(c1.data) == len(c2.data)


class TestChunkFile:
    """Tests for file-based chunking."""

    def test_chunk_file_small(self, tmp_path: Path) -> None:
        """Chunking a small file should work."""
        test_file = tmp_path / "small.bin"
        data = b"small file content"
        test_file.write_bytes(data)

        chunks = list(chunk_file(test_file))
        assert len(chunks) == 1
        assert chunks[0].data == data

    def test_chunk_file_large(self, tmp_path: Path) -> None:
        """Chunking a large file should produce multiple chunks."""
        test_file = tmp_path / "large.bin"
        data = os.urandom(20 * 1024 * 1024)
        test_file.write_bytes(data)

        chunks = list(chunk_file(test_file))
        assert len(chunks) > 1
        reconstructed = b"".join(chunk.data for chunk in chunks)
        assert reconstructed == data

    def test_chunk_file_empty(self, tmp_path: Path) -> None:
        """Chunking an empty file should produce no chunks."""
        test_file = tmp_path / "empty.bin"
        test_file.write_bytes(b"")

        chunks = list(chunk_file(test_file))
        assert len(chunks) == 0

    def test_chunk_file_nonexistent_raises(self, tmp_path: Path) -> None:
        """Chunking a non-existent file should raise FileNotFoundError."""
        with pytest.raises(FileNotFoundError):
            list(chunk_file(tmp_path / "nonexistent.bin"))


class TestChunkDataclass:
    """Tests for Chunk dataclass."""

    def test_chunk_attributes(self) -> None:
        """Chunk should have all required attributes."""
        chunk = Chunk(
            index=0,
            offset=0,
            data=b"test",
            hash="abc123",
        )
        assert chunk.index == 0
        assert chunk.offset == 0
        assert chunk.data == b"test"
        assert chunk.hash == "abc123"

    def test_chunk_size_property(self) -> None:
        """Chunk should have a size property."""
        data = b"test data"
        chunk = Chunk(index=0, offset=0, data=data, hash="x")
        assert chunk.size == len(data)
