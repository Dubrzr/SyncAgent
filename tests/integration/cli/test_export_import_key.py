"""Tests for export-key and import-key commands.

Specs:
- docs/cli/export-key.md
- docs/cli/import-key.md

Test Scenarios:
---------------

export-key:
    - [x] Exports base64-encoded key
    - [x] Requires master password
    - [x] Fails if not initialized
    - [x] Fails with wrong password

import-key:
    - [x] Imports key successfully
    - [x] Changes key ID after import
    - [x] Persists imported key across reload
    - [x] Fails if not initialized
    - [x] Fails with wrong password
    - [x] Fails with invalid base64
    - [x] Fails with wrong key length

Cross-device workflow:
    - [x] Export from A, import to B, both can sync same files
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from syncagent.client.keystore import load_keystore
from tests.integration.cli.fixtures import PatchedCLI, init_client


class TestExportKey:
    """Tests for export-key command."""

    def test_exports_base64_key(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Export should return a valid base64-encoded 32-byte key."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["export-key"], input="testpassword\n")

        assert result.exit_code == 0
        # Extract key from output (last non-empty line)
        lines = [line.strip() for line in result.output.split("\n") if line.strip()]
        exported_key = lines[-1]

        # Should be valid base64
        decoded = base64.b64decode(exported_key)
        assert len(decoded) == 32

    def test_requires_password(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Export should prompt for password."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["export-key"], input="testpassword\n")

        assert "Enter master password" in result.output

    def test_fails_if_not_initialized(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Export should fail if not initialized."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["export-key"])

        assert result.exit_code == 1
        assert "not initialized" in result.output.lower()

    def test_fails_with_wrong_password(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Export should fail with wrong password."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["export-key"], input="wrongpassword\n")

        assert result.exit_code == 1
        assert "invalid password" in result.output.lower()


class TestImportKey:
    """Tests for import-key command."""

    def test_imports_key_successfully(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import should succeed with valid key."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        # Generate a valid key
        new_key = base64.b64encode(os.urandom(32)).decode()

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["import-key", new_key], input="testpassword\n"
            )

        assert result.exit_code == 0
        assert "imported successfully" in result.output.lower()

    def test_changes_key_id(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Import should change the key ID."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        # Get original key ID
        original_keystore = load_keystore("testpassword", config_dir)
        original_key_id = original_keystore.key_id

        # Import new key
        new_key = base64.b64encode(os.urandom(32)).decode()
        with PatchedCLI(config_dir):
            cli_runner.invoke(cli, ["import-key", new_key], input="testpassword\n")

        # Verify key ID changed
        new_keystore = load_keystore("testpassword", config_dir)
        assert new_keystore.key_id != original_key_id

    def test_persists_across_reload(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Imported key should persist and be loadable."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        # Generate and import key
        key_bytes = os.urandom(32)
        new_key = base64.b64encode(key_bytes).decode()

        with PatchedCLI(config_dir):
            cli_runner.invoke(cli, ["import-key", new_key], input="testpassword\n")

        # Reload keystore and verify key matches
        keystore = load_keystore("testpassword", config_dir)
        assert keystore.encryption_key == key_bytes

    def test_fails_if_not_initialized(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import should fail if not initialized."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)

        new_key = base64.b64encode(os.urandom(32)).decode()

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(cli, ["import-key", new_key])

        assert result.exit_code == 1
        assert "not initialized" in result.output.lower()

    def test_fails_with_wrong_password(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import should fail with wrong password."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        new_key = base64.b64encode(os.urandom(32)).decode()

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["import-key", new_key], input="wrongpassword\n"
            )

        assert result.exit_code == 1
        assert "invalid password" in result.output.lower()

    def test_fails_with_invalid_base64(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import should fail with invalid base64."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["import-key", "not-valid-base64!!!"], input="testpassword\n"
            )

        assert result.exit_code == 1
        assert "invalid key" in result.output.lower()

    def test_fails_with_wrong_key_length(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Import should fail if key is not 32 bytes."""
        config_dir = tmp_path / ".syncagent"
        sync_folder = tmp_path / "sync"
        init_client(cli_runner, config_dir, sync_folder)

        short_key = base64.b64encode(b"tooshort").decode()

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["import-key", short_key], input="testpassword\n"
            )

        assert result.exit_code == 1
        assert "32 bytes" in result.output


class TestCrossDeviceWorkflow:
    """Tests for export/import workflow between devices."""

    def test_export_import_enables_sync(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Key exported from A and imported to B should match."""
        # Setup device A
        config_a = tmp_path / "device_a" / ".syncagent"
        sync_a = tmp_path / "device_a" / "sync"
        init_client(cli_runner, config_a, sync_a)

        # Export key from A
        with PatchedCLI(config_a):
            result = cli_runner.invoke(cli, ["export-key"], input="testpassword\n")
        lines = [line.strip() for line in result.output.split("\n") if line.strip()]
        exported_key = lines[-1]

        # Setup device B
        config_b = tmp_path / "device_b" / ".syncagent"
        sync_b = tmp_path / "device_b" / "sync"
        init_client(cli_runner, config_b, sync_b)

        # Import key to B
        with PatchedCLI(config_b):
            result = cli_runner.invoke(
                cli, ["import-key", exported_key], input="testpassword\n"
            )
        assert result.exit_code == 0

        # Verify both have same encryption key
        keystore_a = load_keystore("testpassword", config_a)
        keystore_b = load_keystore("testpassword", config_b)
        assert keystore_a.encryption_key == keystore_b.encryption_key
