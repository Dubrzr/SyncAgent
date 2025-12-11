"""Tests for CLI commands - init, unlock, export-key, import-key."""

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner

from syncagent.client.cli import cli


@pytest.fixture
def runner() -> CliRunner:
    """Create a CLI test runner."""
    return CliRunner()


@pytest.fixture
def config_dir(tmp_path: Path) -> Path:
    """Create a temporary config directory."""
    config = tmp_path / ".syncagent"
    config.mkdir()
    return config


class TestInitCommand:
    """Tests for 'syncagent init' command."""

    def test_init_creates_keystore(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init should create a keystore with keyfile.json."""
        sync_folder = tmp_path / "SyncAgent"
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            # Input: password, confirm password, sync folder (accept default with empty)
            result = runner.invoke(cli, ["init"], input=f"test_password\ntest_password\n{sync_folder}\n")
        assert result.exit_code == 0
        assert (tmp_path / "keyfile.json").exists()

    def test_init_prompts_for_password(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init should prompt for password confirmation."""
        sync_folder = tmp_path / "SyncAgent"
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["init"], input=f"password\npassword\n{sync_folder}\n")
        assert result.exit_code == 0
        assert "password" in result.output.lower() or "mot de passe" in result.output.lower()

    def test_init_fails_on_password_mismatch(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Init should fail if passwords don't match."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["init"], input="password1\npassword2\n")
        assert result.exit_code != 0
        assert not (tmp_path / "keyfile.json").exists()

    def test_init_fails_if_already_initialized(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Init should fail if keystore already exists."""
        sync_folder = tmp_path / "SyncAgent"
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            # First init
            runner.invoke(cli, ["init"], input=f"password\npassword\n{sync_folder}\n")
            # Second init should fail (no more prompts after error)
            result = runner.invoke(cli, ["init"], input="password\npassword\n")
        assert result.exit_code != 0
        assert "already" in result.output.lower() or "existe" in result.output.lower()

    def test_init_shows_key_id(self, runner: CliRunner, tmp_path: Path) -> None:
        """Init should display the key ID."""
        sync_folder = tmp_path / "SyncAgent"
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["init"], input=f"password\npassword\n{sync_folder}\n")
        # Key ID is a UUID
        assert result.exit_code == 0
        # Check output contains something that looks like a UUID
        import re

        uuid_pattern = r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"
        assert re.search(uuid_pattern, result.output.lower())


class TestUnlockCommand:
    """Tests for 'syncagent unlock' command."""

    def test_unlock_with_correct_password(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Unlock should succeed with correct password."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            # password + confirm + sync folder (accept default)
            runner.invoke(cli, ["init"], input="correct_password\ncorrect_password\n\n")
            result = runner.invoke(cli, ["unlock"], input="correct_password\n")
        assert result.exit_code == 0

    def test_unlock_with_wrong_password(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Unlock should fail with wrong password."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="correct_password\ncorrect_password\n\n")
            result = runner.invoke(cli, ["unlock"], input="wrong_password\n")
        assert result.exit_code != 0

    def test_unlock_without_init(self, runner: CliRunner, tmp_path: Path) -> None:
        """Unlock should fail if not initialized."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            result = runner.invoke(cli, ["unlock"], input="password\n")
        assert result.exit_code != 0


class TestExportKeyCommand:
    """Tests for 'syncagent export-key' command."""

    def test_export_key_outputs_base64(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Export-key should output base64-encoded key."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="password\npassword\n\n")
            result = runner.invoke(cli, ["export-key"], input="password\n")
        assert result.exit_code == 0
        # Should contain base64 (44 chars for 32 bytes)
        import base64

        # Find the base64 key in output
        lines = result.output.strip().split("\n")
        key_line = [line for line in lines if len(line) == 44 and "=" in line]
        assert len(key_line) >= 1
        # Verify it's valid base64
        decoded = base64.b64decode(key_line[0])
        assert len(decoded) == 32

    def test_export_key_requires_password(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Export-key should require password."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="password\npassword\n\n")
            result = runner.invoke(cli, ["export-key"], input="wrong_password\n")
        assert result.exit_code != 0


class TestImportKeyCommand:
    """Tests for 'syncagent import-key' command."""

    def test_import_key_updates_keystore(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import-key should update the encryption key."""
        import base64
        import os

        new_key = base64.b64encode(os.urandom(32)).decode()

        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="password\npassword\n\n")
            result = runner.invoke(
                cli, ["import-key", new_key], input="password\n"
            )
        assert result.exit_code == 0

    def test_import_key_invalid_format(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import-key should fail with invalid key format."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="password\npassword\n\n")
            result = runner.invoke(
                cli, ["import-key", "not-valid-base64!!!"], input="password\n"
            )
        assert result.exit_code != 0

    def test_import_key_wrong_length(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import-key should fail if key is not 32 bytes."""
        import base64

        short_key = base64.b64encode(b"short").decode()

        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path):
            runner.invoke(cli, ["init"], input="password\npassword\n\n")
            result = runner.invoke(
                cli, ["import-key", short_key], input="password\n"
            )
        assert result.exit_code != 0

    def test_import_and_export_roundtrip(
        self, runner: CliRunner, tmp_path: Path
    ) -> None:
        """Exported key from one keystore should import into another."""
        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path / "ks1"):
            runner.invoke(cli, ["init"], input="password1\npassword1\n\n")
            export_result = runner.invoke(cli, ["export-key"], input="password1\n")

        # Extract the key from output
        lines = export_result.output.strip().split("\n")
        key_line = [line for line in lines if len(line) == 44 and "=" in line][0]

        with patch("syncagent.client.cli.get_config_dir", return_value=tmp_path / "ks2"):
            runner.invoke(cli, ["init"], input="password2\npassword2\n\n")
            result = runner.invoke(
                cli, ["import-key", key_line], input="password2\n"
            )

        assert result.exit_code == 0
