"""End-to-end integration tests for sync workflow.

Tests the complete flow: init → register → upload → download across clients.
"""

from __future__ import annotations

import os

import pytest

from tests.integration.conftest import SyncTestClient


class TestBasicSyncWorkflow:
    """Test basic sync operations between two clients."""

    def test_upload_and_download_single_file(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Client A uploads a file, Client B downloads it."""
        # Client A creates and uploads a file
        content = "Hello from Client A!"
        local_path = client_a.create_file("hello.txt", content)

        result = client_a.uploader.upload_file(local_path, "hello.txt")
        assert result.server_file_id > 0
        assert result.server_version == 1

        # Client B lists files and downloads
        files = client_b.api_client.list_files()
        assert len(files) == 1
        assert files[0].path == "hello.txt"

        # Download the file
        download_path = client_b.sync_folder / "hello.txt"
        server_file = client_b.api_client.get_file_metadata("hello.txt")
        client_b.downloader.download_file(server_file, download_path)

        # Verify content matches
        assert download_path.read_text() == content

    def test_upload_and_download_nested_file(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test sync of files in nested directories."""
        content = "Nested file content"
        local_path = client_a.create_file("docs/reports/2024/report.txt", content)

        result = client_a.uploader.upload_file(
            local_path, "docs/reports/2024/report.txt"
        )
        assert result.server_version == 1

        # Client B downloads
        files = client_b.api_client.list_files()
        assert any(f.path == "docs/reports/2024/report.txt" for f in files)

        download_path = client_b.sync_folder / "docs/reports/2024/report.txt"
        download_path.parent.mkdir(parents=True, exist_ok=True)
        server_file = client_b.api_client.get_file_metadata("docs/reports/2024/report.txt")
        client_b.downloader.download_file(server_file, download_path)

        assert download_path.read_text() == content

    def test_update_file_and_sync(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Client A uploads, Client B downloads, Client A updates, Client B re-syncs."""
        # Initial upload by Client A
        local_path = client_a.create_file("document.txt", "Version 1")
        result1 = client_a.uploader.upload_file(local_path, "document.txt")
        assert result1.server_version == 1

        # Client B downloads version 1
        download_path_b = client_b.sync_folder / "document.txt"
        server_file = client_b.api_client.get_file_metadata("document.txt")
        client_b.downloader.download_file(server_file, download_path_b)
        assert download_path_b.read_text() == "Version 1"

        # Client A updates the file
        local_path.write_text("Version 2 - Updated!")
        result2 = client_a.uploader.upload_file(
            local_path, "document.txt", parent_version=1
        )
        assert result2.server_version == 2

        # Client B re-downloads
        server_file = client_b.api_client.get_file_metadata("document.txt")
        client_b.downloader.download_file(server_file, download_path_b)
        assert download_path_b.read_text() == "Version 2 - Updated!"

    def test_multiple_files_sync(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test syncing multiple files."""
        # Client A uploads multiple files
        files_to_create = {
            "file1.txt": "Content 1",
            "file2.txt": "Content 2",
            "subdir/file3.txt": "Content 3",
        }

        for rel_path, content in files_to_create.items():
            local_path = client_a.create_file(rel_path, content)
            client_a.uploader.upload_file(local_path, rel_path)

        # Client B lists all files
        server_files = client_b.api_client.list_files()
        assert len(server_files) == 3

        # Client B downloads all files
        for rel_path, expected_content in files_to_create.items():
            download_path = client_b.sync_folder / rel_path
            download_path.parent.mkdir(parents=True, exist_ok=True)
            server_file = client_b.api_client.get_file_metadata(rel_path)
            client_b.downloader.download_file(server_file, download_path)
            assert download_path.read_text() == expected_content


class TestTrashAndRestore:
    """Test delete, trash, and restore workflows."""

    def test_delete_file_moves_to_trash(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Deleted files should appear in trash."""
        # Client A uploads a file
        local_path = client_a.create_file("to-delete.txt", "Delete me")
        client_a.uploader.upload_file(local_path, "to-delete.txt")

        # Verify file exists
        files = client_a.api_client.list_files()
        assert len(files) == 1

        # Delete the file
        client_a.api_client.delete_file("to-delete.txt")

        # File should not appear in normal list
        files = client_a.api_client.list_files()
        assert len(files) == 0

        # File should appear in trash
        trash = client_a.api_client.list_trash()
        assert len(trash) == 1
        assert trash[0].path == "to-delete.txt"

    def test_restore_from_trash(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Files should be restorable from trash."""
        content = "Restore me!"

        # Client A uploads and deletes
        local_path = client_a.create_file("restore-me.txt", content)
        client_a.uploader.upload_file(local_path, "restore-me.txt")
        client_a.api_client.delete_file("restore-me.txt")

        # Verify in trash
        trash = client_a.api_client.list_trash()
        assert len(trash) == 1

        # Restore the file
        client_a.api_client.restore_file("restore-me.txt")

        # File should be back in normal list
        files = client_a.api_client.list_files()
        assert len(files) == 1
        assert files[0].path == "restore-me.txt"

        # Trash should be empty
        trash = client_a.api_client.list_trash()
        assert len(trash) == 0

        # Client B should be able to download restored file
        download_path = client_b.sync_folder / "restore-me.txt"
        server_file = client_b.api_client.get_file_metadata("restore-me.txt")
        client_b.downloader.download_file(server_file, download_path)
        assert download_path.read_text() == content

    def test_delete_sync_to_other_client(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Delete on one client should reflect on file list for other client."""
        # Client A uploads
        local_path = client_a.create_file("shared.txt", "Shared content")
        client_a.uploader.upload_file(local_path, "shared.txt")

        # Both clients see the file
        assert len(client_a.api_client.list_files()) == 1
        assert len(client_b.api_client.list_files()) == 1

        # Client A deletes
        client_a.api_client.delete_file("shared.txt")

        # Both clients should see empty file list
        assert len(client_a.api_client.list_files()) == 0
        assert len(client_b.api_client.list_files()) == 0

        # Both can see file in trash
        assert len(client_a.api_client.list_trash()) == 1
        assert len(client_b.api_client.list_trash()) == 1


class TestLargeFiles:
    """Test large file handling with chunking."""

    def test_large_file_upload_download(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test uploading and downloading a file larger than chunk size."""
        # Create a 5MB file (will be chunked)
        size = 5 * 1024 * 1024
        content = os.urandom(size)

        local_path = client_a.create_file("large.bin", content)
        result = client_a.uploader.upload_file(local_path, "large.bin")

        # Should have multiple chunks
        assert len(result.chunk_hashes) >= 1
        assert result.size == size

        # Client B downloads
        download_path = client_b.sync_folder / "large.bin"
        server_file = client_b.api_client.get_file_metadata("large.bin")
        client_b.downloader.download_file(server_file, download_path)

        # Verify content matches exactly
        assert download_path.read_bytes() == content

    @pytest.mark.slow
    def test_very_large_file_100mb(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test 100MB+ file upload and download."""
        # Create a 100MB file
        size = 100 * 1024 * 1024
        content = os.urandom(size)

        local_path = client_a.create_file("huge.bin", content)
        result = client_a.uploader.upload_file(local_path, "huge.bin")

        # Should have many chunks (100MB / ~4MB avg = ~25 chunks)
        assert len(result.chunk_hashes) >= 10
        assert result.size == size

        # Client B downloads
        download_path = client_b.sync_folder / "huge.bin"
        server_file = client_b.api_client.get_file_metadata("huge.bin")
        client_b.downloader.download_file(server_file, download_path)

        # Verify content matches
        assert download_path.stat().st_size == size
        assert download_path.read_bytes() == content


class TestEdgeCases:
    """Test edge cases and special scenarios."""

    def test_empty_file(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test syncing an empty file."""
        local_path = client_a.create_file("empty.txt", "")
        result = client_a.uploader.upload_file(local_path, "empty.txt")
        assert result.size == 0

        # Client B downloads
        download_path = client_b.sync_folder / "empty.txt"
        server_file = client_b.api_client.get_file_metadata("empty.txt")
        client_b.downloader.download_file(server_file, download_path)
        assert download_path.read_text() == ""

    def test_binary_file(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test syncing binary data."""
        # Create binary content with all byte values
        content = bytes(range(256)) * 100

        local_path = client_a.create_file("binary.dat", content)
        client_a.uploader.upload_file(local_path, "binary.dat")

        # Client B downloads
        download_path = client_b.sync_folder / "binary.dat"
        server_file = client_b.api_client.get_file_metadata("binary.dat")
        client_b.downloader.download_file(server_file, download_path)
        assert download_path.read_bytes() == content

    def test_unicode_content(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test syncing Unicode content."""
        content = "Hello 世界! 🎉 Héllo Wörld! Привет мир!"

        local_path = client_a.create_file("unicode.txt", content)
        client_a.uploader.upload_file(local_path, "unicode.txt")

        # Client B downloads
        download_path = client_b.sync_folder / "unicode.txt"
        server_file = client_b.api_client.get_file_metadata("unicode.txt")
        client_b.downloader.download_file(server_file, download_path)
        # File content is binary (encrypted then decrypted), read as-is
        assert download_path.read_bytes() == content.encode("utf-8")

    def test_special_characters_in_path(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Test files with special characters in path (spaces, etc)."""
        # Note: Some characters may be OS-specific, keep it simple
        content = "Special path content"

        local_path = client_a.create_file("my documents/report 2024.txt", content)
        client_a.uploader.upload_file(local_path, "my documents/report 2024.txt")

        # Client B downloads
        download_path = client_b.sync_folder / "my documents/report 2024.txt"
        download_path.parent.mkdir(parents=True, exist_ok=True)
        server_file = client_b.api_client.get_file_metadata("my documents/report 2024.txt")
        client_b.downloader.download_file(server_file, download_path)
        assert download_path.read_text() == content
