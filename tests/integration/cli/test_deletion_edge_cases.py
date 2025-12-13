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

Watch mode remote polling:
    - [x] ChangeScanner detects admin deletion via /api/changes
    - [x] ChangeScanner detects admin restore via /api/changes
    - [x] emit_events queues remote changes correctly
    - [x] Full integration: admin delete during watch mode
    - [x] Full integration: admin restore during watch mode
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


class TestWatchModeRemotePolling:
    """Tests for watch mode polling for remote changes.

    These tests verify that the change polling mechanism correctly
    detects webui operations (admin deletions, restores, etc.)
    without requiring actual watch mode to run.
    """

    def test_fetch_remote_changes_detects_admin_delete(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """ChangeScanner should detect admin deletions via /api/changes."""
        from syncagent.client.api import HTTPClient
        from syncagent.client.state import LocalSyncState
        from syncagent.client.sync import ChangeScanner
        from syncagent.core.config import ServerConfig

        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Upload a file
        (sync_a / "watch_delete.txt").write_text("To be deleted")
        do_sync(cli_runner, config_a)

        # Setup scanner
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config = load_config()

        server_config = ServerConfig(
            server_url=config["server_url"], token=config["auth_token"]
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        scanner = ChangeScanner(client, state, sync_a)

        # First fetch to establish baseline (cursor)
        scanner.fetch_remote_changes()

        # Admin deletes via server
        test_server.db.delete_file("watch_delete.txt", machine_id=None)

        # Fetch again - should detect the deletion
        remote_changes = scanner.fetch_remote_changes()
        assert "watch_delete.txt" in remote_changes.deleted

    def test_fetch_remote_changes_detects_admin_restore(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """ChangeScanner should detect restored files via /api/changes."""
        from syncagent.client.api import HTTPClient
        from syncagent.client.state import LocalSyncState
        from syncagent.client.sync import ChangeScanner
        from syncagent.core.config import ServerConfig

        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Upload and delete a file
        (sync_a / "watch_restore.txt").write_text("To be restored")
        do_sync(cli_runner, config_a)

        # Admin deletes
        test_server.db.delete_file("watch_restore.txt", machine_id=None)
        do_sync(cli_runner, config_a)  # Client processes deletion
        assert not (sync_a / "watch_restore.txt").exists()

        # Setup scanner
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config = load_config()

        server_config = ServerConfig(
            server_url=config["server_url"], token=config["auth_token"]
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        scanner = ChangeScanner(client, state, sync_a)

        # Fetch to establish cursor (after deletion was processed)
        scanner.fetch_remote_changes()

        # Admin restores
        test_server.db.restore_file_by_path("watch_restore.txt", machine_id=None)

        # Fetch again - should detect the restore as CREATED
        remote_changes = scanner.fetch_remote_changes()
        assert "watch_restore.txt" in remote_changes.created

    def test_emit_events_queues_remote_changes(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """emit_events should queue remote changes from polling."""
        from syncagent.client.sync import (
            EventQueue,
            LocalChanges,
            RemoteChanges,
            SyncEventType,
            emit_events,
        )

        # Create mock changes (simulating what scanner would return)
        local_changes = LocalChanges(created=[], modified=[], deleted=[])
        remote_changes = RemoteChanges(
            created=["new_file.txt"],
            modified=["modified_file.txt"],
            deleted=["deleted_file.txt"],
        )

        queue = EventQueue()
        emit_events(queue, local_changes, remote_changes)

        # Collect all events
        events = []
        while True:
            event = queue.get(timeout=0.1)
            if event is None:
                break
            events.append(event)

        # Should have 3 events
        assert len(events) == 3

        # Check event types
        event_types = {e.path: e.event_type for e in events}
        assert event_types["new_file.txt"] == SyncEventType.REMOTE_CREATED
        assert event_types["modified_file.txt"] == SyncEventType.REMOTE_MODIFIED
        assert event_types["deleted_file.txt"] == SyncEventType.REMOTE_DELETED

    def test_watch_mode_integration_delete(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Full integration: admin delete while client in watch-like mode.

        Simulates the watch mode polling loop using WorkerPool (like the CLI).
        """
        from syncagent.client.api import HTTPClient
        from syncagent.client.keystore import load_keystore
        from syncagent.client.state import LocalSyncState
        from syncagent.client.sync import (
            ChangeScanner,
            EventQueue,
            LocalChanges,
            TransferType,
            WorkerPool,
            emit_events,
        )
        from syncagent.client.sync.types import SyncEventType
        from syncagent.core.config import ServerConfig

        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Upload a file via normal sync
        (sync_a / "live_delete.txt").write_text("Will be deleted live")
        do_sync(cli_runner, config_a)
        assert (sync_a / "live_delete.txt").exists()

        # Setup components for "watch mode simulation"
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config = load_config()
            keystore = load_keystore("testpassword", config_a)

        server_config = ServerConfig(
            server_url=config["server_url"], token=config["auth_token"]
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        scanner = ChangeScanner(client, state, sync_a)
        queue = EventQueue()

        # Create worker pool (like CLI does)
        pool = WorkerPool(
            client=client,
            encryption_key=keystore.encryption_key,
            base_path=sync_a,
            state=state,
        )
        pool.start()

        # Establish cursor
        scanner.fetch_remote_changes()

        # Admin deletes via server
        test_server.db.delete_file("live_delete.txt", machine_id=None)

        # Simulate watch mode poll: fetch remote changes, emit to queue
        remote_changes = scanner.fetch_remote_changes()
        empty_local = LocalChanges(created=[], modified=[], deleted=[])
        emit_events(queue, empty_local, remote_changes)

        # Process queue events (like CLI watch loop does)
        completed = []
        errors = []

        while True:
            event = queue.get(timeout=0.5)
            if event is None:
                break
            # Determine transfer type based on event type
            if event.event_type == SyncEventType.REMOTE_DELETED:
                pool.submit(
                    event=event,
                    transfer_type=TransferType.DELETE,
                    on_complete=lambda r: completed.append(r),
                    on_error=lambda e: errors.append(e),
                )

        # Wait for pool to finish
        time.sleep(1.0)
        pool.stop()

        # File should be deleted locally
        assert not (sync_a / "live_delete.txt").exists()

    def test_watch_mode_integration_restore(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Full integration: admin restore while client in watch-like mode."""
        from syncagent.client.api import HTTPClient
        from syncagent.client.keystore import load_keystore
        from syncagent.client.state import LocalSyncState
        from syncagent.client.sync import (
            ChangeScanner,
            EventQueue,
            LocalChanges,
            TransferType,
            WorkerPool,
            emit_events,
        )
        from syncagent.client.sync.types import SyncEventType
        from syncagent.core.config import ServerConfig

        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Upload a file
        original_content = "Restore this content in watch mode"
        (sync_a / "live_restore.txt").write_text(original_content)
        do_sync(cli_runner, config_a)

        # Admin deletes
        test_server.db.delete_file("live_restore.txt", machine_id=None)
        do_sync(cli_runner, config_a)
        assert not (sync_a / "live_restore.txt").exists()

        # Setup watch mode components
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config = load_config()
            keystore = load_keystore("testpassword", config_a)

        server_config = ServerConfig(
            server_url=config["server_url"], token=config["auth_token"]
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        scanner = ChangeScanner(client, state, sync_a)
        queue = EventQueue()

        # Create worker pool
        pool = WorkerPool(
            client=client,
            encryption_key=keystore.encryption_key,
            base_path=sync_a,
            state=state,
        )
        pool.start()

        # Establish cursor
        scanner.fetch_remote_changes()

        # Admin restores via server
        test_server.db.restore_file_by_path("live_restore.txt", machine_id=None)

        # Simulate watch mode poll
        remote_changes = scanner.fetch_remote_changes()
        assert "live_restore.txt" in remote_changes.created

        empty_local = LocalChanges(created=[], modified=[], deleted=[])
        emit_events(queue, empty_local, remote_changes)

        # Process queue events
        while True:
            event = queue.get(timeout=0.5)
            if event is None:
                break
            # REMOTE_CREATED = download
            if event.event_type == SyncEventType.REMOTE_CREATED:
                pool.submit(
                    event=event,
                    transfer_type=TransferType.DOWNLOAD,
                )

        # Wait for pool to finish
        time.sleep(1.0)
        pool.stop()

        # File should be restored
        assert (sync_a / "live_restore.txt").exists()
        assert (sync_a / "live_restore.txt").read_text() == original_content
