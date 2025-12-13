"""Tests for 'syncagent init', 'reset', and 'unlock' commands.

Spec: docs/cli/init.md, docs/cli/reset.md, docs/cli/unlock.md

Test Scenarios:
---------------

init:
    - [x] Creates keyfile.json and config.json
    - [x] Shows success message with Key ID
    - [x] Saves sync_folder in config
    - [x] Creates sync folder if it doesn't exist
    - [x] Fails if already initialized

reset:
    - [x] --force removes config directory
    - [x] Requires confirmation without --force
    - [x] Confirmation 'y' removes config
    - [x] Does not delete sync folder
    - [x] Says "nothing to reset" if not initialized

unlock:
    - [x] Succeeds with correct password, shows Key ID
    - [x] Fails with wrong password
    - [x] Fails if not initialized
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI


class TestInit:
    """Test 'syncagent init' command."""

    def test_creates_keyfile_and_config(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            assert result.exit_code == 0, f"init failed: {result.output}"
            assert (test_config_dir / "keyfile.json").exists()
            assert (test_config_dir / "config.json").exists()

    def test_shows_success_with_key_id(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            assert "SyncAgent initialized successfully!" in result.output
            assert "Key ID:" in result.output

    def test_saves_sync_folder_in_config(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        import json

        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            config = json.loads((test_config_dir / "config.json").read_text())
            assert config["sync_folder"] == str(test_sync_folder)

    def test_creates_sync_folder_if_missing(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        tmp_path: Path,
    ) -> None:
        sync_folder = tmp_path / "new_sync"
        assert not sync_folder.exists()

        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{sync_folder}\n",
            )

            assert sync_folder.exists()

    def test_fails_if_already_initialized(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            assert result.exit_code == 1
            assert "already initialized" in result.output.lower()


class TestReset:
    """Test 'syncagent reset' command."""

    def test_force_removes_config_dir(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(cli, ["reset", "--force"])

            assert result.exit_code == 0
            assert not test_config_dir.exists()

    def test_requires_confirmation(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(cli, ["reset"], input="n\n")

            assert (test_config_dir / "keyfile.json").exists()
            assert "aborted" in result.output.lower()

    def test_confirmation_yes_removes_config(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(cli, ["reset"], input="y\n")

            assert result.exit_code == 0
            assert not test_config_dir.exists()

    def test_does_not_delete_sync_folder(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        test_file = test_sync_folder / "important.txt"
        test_file.write_text("Important data")

        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )
            cli_runner.invoke(cli, ["reset", "--force"])

            assert test_sync_folder.exists()
            assert test_file.read_text() == "Important data"

    def test_nothing_to_reset_if_not_initialized(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
    ) -> None:
        import shutil
        if test_config_dir.exists():
            shutil.rmtree(test_config_dir)

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(cli, ["reset"])

            assert "nothing to reset" in result.output.lower()


class TestUnlock:
    """Test 'syncagent unlock' command."""

    def test_succeeds_with_correct_password(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(cli, ["unlock"], input="testpassword\n")

            assert result.exit_code == 0
            assert "unlocked" in result.output.lower()
            assert "Key ID:" in result.output

    def test_fails_with_wrong_password(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli, ["init"],
                input=f"testpassword\ntestpassword\n{test_sync_folder}\n",
            )

            result = cli_runner.invoke(cli, ["unlock"], input="wrongpassword\n")

            assert result.exit_code == 1
            assert "error" in result.output.lower()

    def test_fails_if_not_initialized(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
    ) -> None:
        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(cli, ["unlock"], input="testpassword\n")

            assert result.exit_code == 1
            assert "not initialized" in result.output.lower()
