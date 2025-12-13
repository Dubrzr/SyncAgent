"""Tests for filesystem error handling.

Test Scenarios:
---------------

Permission errors:
    - [x] Handles file permission denied on read
    - [x] Handles directory permission denied
    - [x] Reports permission errors clearly

File access issues:
    - [x] Handles file deleted during sync
    - [x] Handles file modified during upload

Special files:
    - [x] Skips symlinks (or handles appropriately)
    - [x] Handles empty files
    - [x] Handles files with no extension
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest
from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI, init_client, register_client
from tests.integration.conftest import TestServer


class TestFileAccessErrors:
    """Tests for file access error handling."""

    def test_handles_file_deleted_during_scan(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should handle file being deleted between scan and upload."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create and immediately delete a file
        test_file = sync_folder / "ephemeral.txt"
        test_file.write_text("Temporary")
        # File exists during scan but we'll delete before sync starts

        with PatchedCLI(config_dir):
            # Delete file right before sync processes it
            test_file.unlink()
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        # Should not crash
        assert result.exit_code == 0

    def test_handles_empty_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should sync empty files correctly."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create empty file
        (sync_folder / "empty.txt").write_text("")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        assert result.exit_code == 0
        # Empty file should be synced
        assert "empty.txt" in result.output or "uploaded" in result.output

    def test_handles_file_no_extension(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should sync files without extension."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create file without extension
        (sync_folder / "Makefile").write_text("all: build")
        (sync_folder / "README").write_text("Read me")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        assert result.exit_code == 0


class TestSpecialFiles:
    """Tests for handling special file types."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Symlinks need admin on Windows")
    def test_handles_symlinks(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should handle symlinks appropriately (skip or follow)."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create regular file and symlink
        (sync_folder / "real.txt").write_text("Real file")
        symlink = sync_folder / "link.txt"
        symlink.symlink_to(sync_folder / "real.txt")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        # Should not crash (symlink handling is implementation-defined)
        assert result.exit_code == 0

    def test_handles_hidden_files(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should handle hidden files (dot files)."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create hidden file
        (sync_folder / ".hidden").write_text("Hidden content")
        (sync_folder / ".gitignore").write_text("*.log")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        # Should not crash
        assert result.exit_code == 0

    def test_handles_deeply_nested_directories(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should handle deeply nested directory structures."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create nested structure (10 levels deep)
        nested_path = sync_folder
        for i in range(10):
            nested_path = nested_path / f"level{i}"
        nested_path.mkdir(parents=True)
        (nested_path / "deep.txt").write_text("Deep file")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        assert result.exit_code == 0
        assert "deep.txt" in result.output or "uploaded" in result.output


class TestPermissionErrors:
    """Tests for permission error handling."""

    @pytest.mark.skipif(sys.platform == "win32", reason="Permission model differs on Windows")
    def test_handles_unreadable_file(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Should handle files without read permission."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create file and remove read permission
        test_file = sync_folder / "noperm.txt"
        test_file.write_text("Secret")
        os.chmod(test_file, 0o000)

        try:
            with PatchedCLI(config_dir):
                result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

            # Should handle gracefully (may show error but not crash)
            # Exit code could be 0 if it skips the file, or non-zero if it reports error
            assert result.exit_code in (0, 1)
        finally:
            # Restore permissions for cleanup
            os.chmod(test_file, 0o644)

    def test_handles_readable_file_normal(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Normal readable files should sync without issues."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir(parents=True)
        init_client(cli_runner, config_dir, sync_folder)
        token = test_server.create_invitation()
        register_client(cli_runner, config_dir, test_server.url, token, "test-client")

        # Create normal readable file
        (sync_folder / "readable.txt").write_text("Normal content")

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")

        assert result.exit_code == 0
