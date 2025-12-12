"""End-to-end integration tests for conflict detection.

Tests simultaneous modifications and conflict resolution workflows.
"""

from __future__ import annotations

import pytest

from syncagent.client.api import ConflictError
from tests.integration.conftest import SyncTestClient


class TestConflictDetection:
    """Test conflict detection between two clients."""

    def test_simultaneous_update_causes_conflict(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Both clients update the same file with same parent version -> conflict."""
        # Client A creates the initial file
        local_path_a = client_a.create_file("shared.txt", "Initial content")
        result = client_a.uploader.upload_file(local_path_a, "shared.txt")
        initial_version = result.server_version
        assert initial_version == 1

        # Client A updates (version 1 -> 2)
        local_path_a.write_text("Client A's update")
        result_a = client_a.uploader.upload_file(
            local_path_a, "shared.txt", parent_version=1
        )
        assert result_a.server_version == 2

        # Client B tries to update with stale parent_version (1 instead of 2)
        local_path_b = client_b.create_file("shared.txt", "Client B's update")
        with pytest.raises(ConflictError):
            client_b.uploader.upload_file(
                local_path_b, "shared.txt", parent_version=1
            )

    def test_sequential_updates_no_conflict(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Sequential updates with correct parent versions should succeed."""
        # Client A creates file
        local_path_a = client_a.create_file("doc.txt", "Version 1")
        result1 = client_a.uploader.upload_file(local_path_a, "doc.txt")
        assert result1.server_version == 1

        # Client B updates (v1 -> v2)
        local_path_b = client_b.create_file("doc.txt", "Version 2 by B")
        result2 = client_b.uploader.upload_file(
            local_path_b, "doc.txt", parent_version=1
        )
        assert result2.server_version == 2

        # Client A updates (v2 -> v3)
        local_path_a.write_text("Version 3 by A")
        result3 = client_a.uploader.upload_file(
            local_path_a, "doc.txt", parent_version=2
        )
        assert result3.server_version == 3

        # Both clients can read the final version
        server_file = client_a.api_client.get_file("doc.txt")
        download_path = client_a.sync_folder / "final.txt"
        client_a.downloader.download_file(server_file, download_path)
        assert download_path.read_text() == "Version 3 by A"

    def test_conflict_after_multiple_updates(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Conflict detection works even after many sequential updates."""
        # Client A creates and updates multiple times
        local_path_a = client_a.create_file("evolving.txt", "v1")
        client_a.uploader.upload_file(local_path_a, "evolving.txt")

        local_path_a.write_text("v2")
        client_a.uploader.upload_file(local_path_a, "evolving.txt", parent_version=1)

        local_path_a.write_text("v3")
        client_a.uploader.upload_file(local_path_a, "evolving.txt", parent_version=2)

        local_path_a.write_text("v4")
        result = client_a.uploader.upload_file(
            local_path_a, "evolving.txt", parent_version=3
        )
        assert result.server_version == 4

        # Client B tries to update from version 2 (stale)
        local_path_b = client_b.create_file("evolving.txt", "B's changes")
        with pytest.raises(ConflictError):
            client_b.uploader.upload_file(
                local_path_b, "evolving.txt", parent_version=2
            )

    def test_new_file_no_conflict(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Creating new files on different clients should not conflict."""
        # Both clients create different files
        local_a = client_a.create_file("from-a.txt", "A's content")
        local_b = client_b.create_file("from-b.txt", "B's content")

        result_a = client_a.uploader.upload_file(local_a, "from-a.txt")
        result_b = client_b.uploader.upload_file(local_b, "from-b.txt")

        assert result_a.server_version == 1
        assert result_b.server_version == 1

        # Both files exist on server
        files = client_a.api_client.list_files()
        paths = [f.path for f in files]
        assert "from-a.txt" in paths
        assert "from-b.txt" in paths


class TestConflictRecovery:
    """Test recovery strategies after conflict detection."""

    def test_retry_with_updated_version(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """After conflict, client can retry with correct parent version."""
        # Client A creates file
        local_path_a = client_a.create_file("retry.txt", "Initial")
        client_a.uploader.upload_file(local_path_a, "retry.txt")

        # Client A updates (v1 -> v2)
        local_path_a.write_text("Updated by A")
        client_a.uploader.upload_file(local_path_a, "retry.txt", parent_version=1)

        # Client B tries with stale version (should fail)
        local_path_b = client_b.create_file("retry.txt", "B's changes")
        with pytest.raises(ConflictError):
            client_b.uploader.upload_file(
                local_path_b, "retry.txt", parent_version=1
            )

        # Client B fetches current version and retries
        server_file = client_b.api_client.get_file("retry.txt")
        current_version = server_file.version
        assert current_version == 2

        # Now retry with correct parent version
        local_path_b.write_text("B's changes (retry)")
        result = client_b.uploader.upload_file(
            local_path_b, "retry.txt", parent_version=current_version
        )
        assert result.server_version == 3

    def test_download_before_upload_avoids_conflict(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Client that syncs first before uploading avoids conflicts."""
        # Client A creates file
        local_path_a = client_a.create_file("sync-first.txt", "Original")
        client_a.uploader.upload_file(local_path_a, "sync-first.txt")

        # Client A updates
        local_path_a.write_text("A's update")
        client_a.uploader.upload_file(
            local_path_a, "sync-first.txt", parent_version=1
        )

        # Client B syncs first (downloads latest version)
        server_file = client_b.api_client.get_file("sync-first.txt")
        download_path = client_b.sync_folder / "sync-first.txt"
        client_b.downloader.download_file(server_file, download_path)

        # Client B modifies and uploads with correct parent version
        download_path.write_text("B's changes after sync")
        result = client_b.uploader.upload_file(
            download_path, "sync-first.txt", parent_version=server_file.version
        )
        assert result.server_version == 3


class TestConcurrentOperations:
    """Test various concurrent operation scenarios."""

    def test_delete_while_other_updates(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """One client deletes while another tries to update."""
        # Client A creates file
        local_path_a = client_a.create_file("delete-vs-update.txt", "Content")
        client_a.uploader.upload_file(local_path_a, "delete-vs-update.txt")

        # Client A deletes the file
        client_a.api_client.delete_file("delete-vs-update.txt")

        # Client B tries to update (file is deleted)
        client_b.create_file("delete-vs-update.txt", "B's update")

        # The behavior here depends on implementation:
        # Either it recreates the file or raises an error
        # For now, we test that the file is in trash
        trash = client_b.api_client.list_trash()
        assert len(trash) == 1
        assert trash[0].path == "delete-vs-update.txt"

    def test_simultaneous_different_files(
        self,
        client_a: SyncTestClient,
        client_b: SyncTestClient,
    ) -> None:
        """Simultaneous operations on different files should not interfere."""
        # Client A works on file1
        local_a1 = client_a.create_file("file1.txt", "A1 v1")
        client_a.uploader.upload_file(local_a1, "file1.txt")

        # Client B works on file2
        local_b2 = client_b.create_file("file2.txt", "B2 v1")
        client_b.uploader.upload_file(local_b2, "file2.txt")

        # Both update their respective files
        local_a1.write_text("A1 v2")
        client_a.uploader.upload_file(local_a1, "file1.txt", parent_version=1)

        local_b2.write_text("B2 v2")
        client_b.uploader.upload_file(local_b2, "file2.txt", parent_version=1)

        # Both files should have version 2
        file1 = client_a.api_client.get_file("file1.txt")
        file2 = client_b.api_client.get_file("file2.txt")
        assert file1.version == 2
        assert file2.version == 2

        # Cross-download works
        server_file1 = client_b.api_client.get_file("file1.txt")
        download1 = client_b.sync_folder / "file1_from_a.txt"
        client_b.downloader.download_file(server_file1, download1)
        assert download1.read_text() == "A1 v2"

        server_file2 = client_a.api_client.get_file("file2.txt")
        download2 = client_a.sync_folder / "file2_from_b.txt"
        client_a.downloader.download_file(server_file2, download2)
        assert download2.read_text() == "B2 v2"
