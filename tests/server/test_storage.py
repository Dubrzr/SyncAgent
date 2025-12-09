"""Tests for block storage implementations."""

from pathlib import Path

import pytest

from syncagent.server.storage import (
    ChunkNotFoundError,
    ChunkStorage,
    LocalFSStorage,
    S3Storage,
    create_storage,
)


class TestLocalFSStorage:
    """Tests for LocalFSStorage implementation."""

    @pytest.fixture
    def storage(self, tmp_path: Path) -> LocalFSStorage:
        """Create a LocalFSStorage instance for testing."""
        return LocalFSStorage(tmp_path / "chunks")

    def test_put_creates_file(self, storage: LocalFSStorage) -> None:
        """put() should create the chunk file."""
        chunk_hash = "a" * 64
        data = b"encrypted chunk data"

        storage.put(chunk_hash, data)

        assert storage.exists(chunk_hash)

    def test_put_creates_subdirectory(self, storage: LocalFSStorage) -> None:
        """put() should create subdirectory based on hash prefix."""
        chunk_hash = "ab" + "c" * 62
        data = b"data"

        storage.put(chunk_hash, data)

        expected_path = storage._base_path / "ab" / f"{chunk_hash}.enc"
        assert expected_path.exists()

    def test_get_returns_data(self, storage: LocalFSStorage) -> None:
        """get() should return the stored data."""
        chunk_hash = "d" * 64
        data = b"test data 12345"

        storage.put(chunk_hash, data)
        result = storage.get(chunk_hash)

        assert result == data

    def test_get_raises_on_missing(self, storage: LocalFSStorage) -> None:
        """get() should raise ChunkNotFoundError for missing chunks."""
        with pytest.raises(ChunkNotFoundError, match="Chunk not found"):
            storage.get("nonexistent" + "0" * 53)

    def test_exists_true(self, storage: LocalFSStorage) -> None:
        """exists() should return True for existing chunks."""
        chunk_hash = "e" * 64
        storage.put(chunk_hash, b"data")

        assert storage.exists(chunk_hash) is True

    def test_exists_false(self, storage: LocalFSStorage) -> None:
        """exists() should return False for missing chunks."""
        assert storage.exists("f" * 64) is False

    def test_delete_removes_file(self, storage: LocalFSStorage) -> None:
        """delete() should remove the chunk file."""
        chunk_hash = "1" * 64
        storage.put(chunk_hash, b"data")

        result = storage.delete(chunk_hash)

        assert result is True
        assert storage.exists(chunk_hash) is False

    def test_delete_returns_false_if_missing(self, storage: LocalFSStorage) -> None:
        """delete() should return False if chunk doesn't exist."""
        result = storage.delete("2" * 64)

        assert result is False

    def test_roundtrip_large_data(self, storage: LocalFSStorage) -> None:
        """Should handle large chunks (simulating 4MB)."""
        chunk_hash = "3" * 64
        data = b"x" * (4 * 1024 * 1024)  # 4 MB

        storage.put(chunk_hash, data)
        result = storage.get(chunk_hash)

        assert result == data

    def test_multiple_chunks(self, storage: LocalFSStorage) -> None:
        """Should handle multiple chunks in different subdirectories."""
        chunks = {
            "aa" + "0" * 62: b"chunk1",
            "bb" + "0" * 62: b"chunk2",
            "cc" + "0" * 62: b"chunk3",
        }

        for chunk_hash, data in chunks.items():
            storage.put(chunk_hash, data)

        for chunk_hash, expected in chunks.items():
            assert storage.get(chunk_hash) == expected


class TestS3Storage:
    """Tests for S3Storage using moto mock."""

    @pytest.fixture
    def mock_s3(self) -> None:
        """Set up moto mock for S3."""
        pytest.importorskip("moto")
        import boto3
        from moto import mock_aws

        with mock_aws():
            # Create the bucket
            client = boto3.client("s3", region_name="us-east-1")
            client.create_bucket(Bucket="test-bucket")
            yield

    @pytest.fixture
    def storage(self, mock_s3: None) -> S3Storage:
        """Create an S3Storage instance for testing."""
        return S3Storage(bucket="test-bucket", region="us-east-1")

    def test_put_and_get(self, storage: S3Storage) -> None:
        """put() and get() should work correctly."""
        chunk_hash = "s3" + "a" * 62
        data = b"s3 encrypted data"

        storage.put(chunk_hash, data)
        result = storage.get(chunk_hash)

        assert result == data

    def test_get_raises_on_missing(self, storage: S3Storage) -> None:
        """get() should raise ChunkNotFoundError for missing chunks."""
        with pytest.raises(ChunkNotFoundError, match="Chunk not found"):
            storage.get("missing" + "0" * 57)

    def test_exists_true(self, storage: S3Storage) -> None:
        """exists() should return True for existing chunks."""
        chunk_hash = "ex" + "b" * 62
        storage.put(chunk_hash, b"data")

        assert storage.exists(chunk_hash) is True

    def test_exists_false(self, storage: S3Storage) -> None:
        """exists() should return False for missing chunks."""
        assert storage.exists("no" + "c" * 62) is False

    def test_delete_removes_object(self, storage: S3Storage) -> None:
        """delete() should remove the S3 object."""
        chunk_hash = "de" + "d" * 62
        storage.put(chunk_hash, b"data")

        result = storage.delete(chunk_hash)

        assert result is True
        assert storage.exists(chunk_hash) is False

    def test_delete_returns_false_if_missing(self, storage: S3Storage) -> None:
        """delete() should return False if object doesn't exist."""
        result = storage.delete("nm" + "e" * 62)

        assert result is False

    def test_key_format(self, storage: S3Storage) -> None:
        """S3 keys should use prefix subdirectory structure."""
        chunk_hash = "ab" + "f" * 62
        expected_key = f"chunks/ab/{chunk_hash}.enc"

        assert storage._key(chunk_hash) == expected_key


class TestCreateStorage:
    """Tests for the create_storage factory function."""

    def test_create_local_storage(self, tmp_path: Path) -> None:
        """Should create LocalFSStorage for type='local'."""
        config = {
            "type": "local",
            "local_path": str(tmp_path / "chunks"),
        }

        storage = create_storage(config)

        assert isinstance(storage, LocalFSStorage)

    def test_create_local_storage_default_path(self) -> None:
        """Should use default path if not specified."""
        config: dict[str, str | None] = {"type": "local"}

        storage = create_storage(config)

        assert isinstance(storage, LocalFSStorage)

    def test_create_s3_storage(self) -> None:
        """Should create S3Storage for type='s3'."""
        pytest.importorskip("moto")
        from moto import mock_aws

        with mock_aws():
            import boto3

            boto3.client("s3", region_name="us-east-1").create_bucket(Bucket="my-bucket")

            config = {
                "type": "s3",
                "bucket": "my-bucket",
                "region": "us-east-1",
            }

            storage = create_storage(config)

            assert isinstance(storage, S3Storage)

    def test_create_s3_requires_bucket(self) -> None:
        """Should raise ValueError if bucket is missing."""
        config: dict[str, str | None] = {"type": "s3"}

        with pytest.raises(ValueError, match="requires 'bucket'"):
            create_storage(config)

    def test_unknown_type_raises(self) -> None:
        """Should raise ValueError for unknown storage type."""
        config = {"type": "unknown"}

        with pytest.raises(ValueError, match="Unknown storage type"):
            create_storage(config)

    def test_default_type_is_local(self, tmp_path: Path) -> None:
        """Should default to local storage if type not specified."""
        config: dict[str, str | None] = {"local_path": str(tmp_path)}

        storage = create_storage(config)

        assert isinstance(storage, LocalFSStorage)


class TestChunkStorageInterface:
    """Verify ChunkStorage is a proper abstract base class."""

    def test_cannot_instantiate_abstract(self) -> None:
        """ChunkStorage cannot be instantiated directly."""
        with pytest.raises(TypeError, match="abstract"):
            ChunkStorage()  # type: ignore[abstract]
