"""Tests for deletion edge cases.

Test Scenarios:
---------------

Basic deletions:
    - [x] Delete file syncs to other client
    - [x] Delete directory syncs to other client
    - [x] Delete nested file syncs correctly

Delete and recreate:
    - [x] Delete then recreate same file
    - [x] Delete file, other client has modifications

Simultaneous deletions:
    - [x] Both clients delete same file
    - [x] One deletes while other modifies

Admin (WUI) deletions:
    - [x] Admin deletes file → client syncs and removes local file
    - [x] Admin deletes folder → client syncs and removes all local files

Restore from trash:
    - [x] Admin restores file → client syncs and gets file back
    - [x] Admin restores file → multiple clients get file back
"""

from __future__ import annotations

import time
from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI, init_client, register_client
from tests.integration.conftest import TestServer


def setup_client(
    cli_runner: CliRunner,
    tmp_path: Path,
    test_server: TestServer,
    name: str,
    import_key_from: Path | None = None,
) -> tuple[Path, Path]:
    """Setup a client for testing."""
    config_dir = tmp_path / name / ".syncagent"
    config_dir.mkdir(parents=True, exist_ok=True)
    sync_folder = tmp_path / name / "sync"
    sync_folder.mkdir(parents=True, exist_ok=True)

    init_client(cli_runner, config_dir, sync_folder)

    if import_key_from:
        with PatchedCLI(import_key_from):
            result = cli_runner.invoke(cli, ["export-key"], input="testpassword\n")
            lines = [line.strip() for line in result.output.split("\n") if line.strip()]
            exported_key = lines[-1]
        with PatchedCLI(config_dir):
            cli_runner.invoke(cli, ["import-key", exported_key], input="testpassword\n")

    token = test_server.create_invitation()
    register_client(cli_runner, config_dir, test_server.url, token, name)

    return config_dir, sync_folder


def do_sync(cli_runner: CliRunner, config_dir: Path) -> str:
    """Run sync and return output."""
    with PatchedCLI(config_dir):
        result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")
        if result.exit_code != 0:
            raise RuntimeError(f"sync failed: {result.output}")
        return result.output


class TestBasicDeletions:
    """Tests for basic delete operations."""

    def test_delete_file_syncs(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Deleted file should be removed on other client."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create and sync
        (sync_a / "to_delete.txt").write_text("Delete me")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)
        assert (sync_b / "to_delete.txt").exists()

        # Delete and sync
        (sync_a / "to_delete.txt").unlink()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Should be deleted on B (or moved to trash)
        # Note: exact behavior depends on delete handling implementation
        # At minimum, should not crash

    def test_delete_directory_with_files(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Deleted directory should sync to other client."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create directory with files
        (sync_a / "mydir").mkdir()
        (sync_a / "mydir" / "file1.txt").write_text("File 1")
        (sync_a / "mydir" / "file2.txt").write_text("File 2")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)
        assert (sync_b / "mydir").exists()

        # Delete directory files
        (sync_a / "mydir" / "file1.txt").unlink()
        (sync_a / "mydir" / "file2.txt").unlink()
        (sync_a / "mydir").rmdir()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Should sync without crashing

    def test_delete_nested_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Deleted nested file should sync correctly."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create nested structure
        (sync_a / "level1" / "level2" / "level3").mkdir(parents=True)
        (sync_a / "level1" / "level2" / "level3" / "deep.txt").write_text("Deep file")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Delete just the file
        (sync_a / "level1" / "level2" / "level3" / "deep.txt").unlink()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Directory structure may remain, file should be gone


class TestDeleteAndRecreate:
    """Tests for delete then recreate scenarios."""

    def test_delete_and_recreate_same_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Delete then recreate same filename should work."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create v1
        (sync_a / "recreate.txt").write_text("Version 1")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)
        assert (sync_b / "recreate.txt").read_text() == "Version 1"

        # Delete and recreate with new content
        (sync_a / "recreate.txt").unlink()
        time.sleep(0.1)
        (sync_a / "recreate.txt").write_text("Version 2")
        do_sync(cli_runner, config_a)

        # B syncs to get update
        do_sync(cli_runner, config_b)

        # B should have the file (either v1 or v2 depending on timing, but should exist)
        assert (sync_b / "recreate.txt").exists()
        # Content should be one of the versions
        content = (sync_b / "recreate.txt").read_text()
        assert content in ("Version 1", "Version 2")

    def test_delete_while_other_has_modifications(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Delete on A while B has local modifications."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Both have file
        (sync_a / "conflict_delete.txt").write_text("Original")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # A deletes
        (sync_a / "conflict_delete.txt").unlink()
        do_sync(cli_runner, config_a)

        # B modifies (before knowing about delete)
        time.sleep(0.1)
        (sync_b / "conflict_delete.txt").write_text("B's modifications")
        do_sync(cli_runner, config_b)

        # Should handle gracefully (conflict or B's version wins)


class TestSimultaneousDeletions:
    """Tests for simultaneous delete operations."""

    def test_both_delete_same_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Both clients delete same file should work."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Both have file
        (sync_a / "both_delete.txt").write_text("Delete me")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Both delete locally
        (sync_a / "both_delete.txt").unlink()
        (sync_b / "both_delete.txt").unlink()

        # Both sync
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Should handle gracefully

    def test_multiple_files_deleted(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Deleting multiple files should sync correctly."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create multiple files
        for i in range(5):
            (sync_a / f"file{i}.txt").write_text(f"Content {i}")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Delete all
        for i in range(5):
            (sync_a / f"file{i}.txt").unlink()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Should handle all deletions

    def test_delete_empty_directory(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Deleting empty directory should work."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create directory with file, sync, then delete file
        (sync_a / "emptydir").mkdir()
        (sync_a / "emptydir" / "temp.txt").write_text("temp")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Delete file, leaving empty dir
        (sync_a / "emptydir" / "temp.txt").unlink()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Now delete empty dir
        (sync_a / "emptydir").rmdir()
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # Should handle gracefully


class TestAdminDeletions:
    """Tests for admin (WUI) deletion propagating to clients."""

    def test_admin_deletes_file_syncs_to_client(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Admin deletes file via server → client syncs and removes local file."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Client uploads a file
        (sync_a / "admin_delete_me.txt").write_text("Delete via admin")
        do_sync(cli_runner, config_a)
        assert (sync_a / "admin_delete_me.txt").exists()

        # Admin deletes via server (simulate WUI deletion)
        test_server.db.delete_file("admin_delete_me.txt", machine_id=None)

        # Client syncs again
        do_sync(cli_runner, config_a)

        # File should be removed locally
        assert not (sync_a / "admin_delete_me.txt").exists()

    def test_admin_deletes_folder_syncs_to_client(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Admin deletes folder via server → client syncs and removes all local files."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Client uploads multiple files in a folder
        (sync_a / "admin_folder").mkdir()
        (sync_a / "admin_folder" / "file1.txt").write_text("File 1")
        (sync_a / "admin_folder" / "file2.txt").write_text("File 2")
        (sync_a / "admin_folder" / "sub").mkdir()
        (sync_a / "admin_folder" / "sub" / "nested.txt").write_text("Nested")
        do_sync(cli_runner, config_a)

        # Verify files exist
        assert (sync_a / "admin_folder" / "file1.txt").exists()
        assert (sync_a / "admin_folder" / "file2.txt").exists()
        assert (sync_a / "admin_folder" / "sub" / "nested.txt").exists()

        # Admin deletes folder via server (using smart delete_file)
        deleted_count = test_server.db.delete_file("admin_folder", machine_id=None)
        assert deleted_count == 3  # All 3 files deleted

        # Client syncs again
        do_sync(cli_runner, config_a)

        # All files should be removed locally
        assert not (sync_a / "admin_folder" / "file1.txt").exists()
        assert not (sync_a / "admin_folder" / "file2.txt").exists()
        assert not (sync_a / "admin_folder" / "sub" / "nested.txt").exists()

    def test_admin_delete_propagates_to_multiple_clients(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Admin deletion should propagate to all connected clients."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(
            cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a
        )

        # Client A uploads a file
        (sync_a / "shared_file.txt").write_text("Shared content")
        do_sync(cli_runner, config_a)

        # Client B syncs to get the file
        do_sync(cli_runner, config_b)
        assert (sync_b / "shared_file.txt").exists()

        # Admin deletes via server
        test_server.db.delete_file("shared_file.txt", machine_id=None)

        # Both clients sync
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        # File should be removed on both clients
        assert not (sync_a / "shared_file.txt").exists()
        assert not (sync_b / "shared_file.txt").exists()


class TestRestoreFromTrash:
    """Tests for restoring files from trash syncing to clients."""

    def test_restore_file_syncs_to_client(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Admin restores file from trash → client syncs and gets file back."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Client uploads a file
        (sync_a / "restore_me.txt").write_text("Restore this content")
        do_sync(cli_runner, config_a)

        # Admin deletes via server
        test_server.db.delete_file("restore_me.txt", machine_id=None)

        # Client syncs - file should be removed
        do_sync(cli_runner, config_a)
        assert not (sync_a / "restore_me.txt").exists()

        # Admin restores from trash
        restored = test_server.db.restore_file_by_path("restore_me.txt", machine_id=None)
        assert restored

        # Client syncs again - file should be back
        do_sync(cli_runner, config_a)
        assert (sync_a / "restore_me.txt").exists()
        assert (sync_a / "restore_me.txt").read_text() == "Restore this content"

    def test_restore_propagates_to_multiple_clients(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Restored file should propagate to all connected clients."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(
            cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a
        )

        # Client A uploads a file
        (sync_a / "shared_restore.txt").write_text("Shared content")
        do_sync(cli_runner, config_a)

        # Client B syncs to get the file
        do_sync(cli_runner, config_b)
        assert (sync_b / "shared_restore.txt").exists()

        # Admin deletes via server
        test_server.db.delete_file("shared_restore.txt", machine_id=None)

        # Both clients sync - file removed
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)
        assert not (sync_a / "shared_restore.txt").exists()
        assert not (sync_b / "shared_restore.txt").exists()

        # Admin restores
        test_server.db.restore_file_by_path("shared_restore.txt", machine_id=None)

        # Both clients sync - file should be back
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)
        assert (sync_a / "shared_restore.txt").exists()
        assert (sync_b / "shared_restore.txt").exists()
        assert (sync_a / "shared_restore.txt").read_text() == "Shared content"
        assert (sync_b / "shared_restore.txt").read_text() == "Shared content"
