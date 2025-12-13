"""Common fixtures and helpers for CLI tests.

These fixtures provide isolated test environments for CLI commands
by patching get_config_dir in all relevant modules.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
from click.testing import CliRunner


@pytest.fixture
def cli_runner() -> CliRunner:
    """Create a CliRunner for testing."""
    return CliRunner()


@pytest.fixture
def test_config_dir(tmp_path: Path) -> Path:
    """Create a test config directory."""
    config_dir = tmp_path / ".syncagent"
    config_dir.mkdir(parents=True, exist_ok=True)
    return config_dir


@pytest.fixture
def test_sync_folder(tmp_path: Path) -> Path:
    """Create a test sync folder."""
    sync_folder = tmp_path / "sync"
    sync_folder.mkdir(parents=True, exist_ok=True)
    return sync_folder


def patch_config_dir(config_dir: Path) -> list:
    """Create patches for get_config_dir in all CLI modules.

    Must be used with start/stop pattern:
        patches = patch_config_dir(config_dir)
        for p in patches:
            p.start()
        try:
            # ... test code ...
        finally:
            for p in patches:
                p.stop()
    """
    return [
        patch("syncagent.client.cli.keystore.get_config_dir", return_value=config_dir),
        patch("syncagent.client.cli.register.get_config_dir", return_value=config_dir),
        patch("syncagent.client.cli.sync.get_config_dir", return_value=config_dir),
        patch("syncagent.client.cli.config.get_config_dir", return_value=config_dir),
    ]


class PatchedCLI:
    """Context manager for CLI tests with patched config directory."""

    def __init__(self, config_dir: Path):
        self.config_dir = config_dir
        self.patches = patch_config_dir(config_dir)

    def __enter__(self):
        for p in self.patches:
            p.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        for p in self.patches:
            p.stop()
        return False


def init_client(
    cli_runner: CliRunner,
    config_dir: Path,
    sync_folder: Path,
    password: str = "testpassword",
) -> None:
    """Initialize a client with the given password and sync folder.

    Args:
        cli_runner: Click test runner
        config_dir: Path to config directory
        sync_folder: Path to sync folder
        password: Master password (default: "testpassword")
    """
    from syncagent.client.cli import cli

    with PatchedCLI(config_dir):
        input_text = f"{password}\n{password}\n{sync_folder}\n"
        result = cli_runner.invoke(cli, ["init"], input=input_text)
        if result.exit_code != 0:
            raise RuntimeError(f"init failed: {result.output}")


def register_client(
    cli_runner: CliRunner,
    config_dir: Path,
    server_url: str,
    invitation_token: str,
    machine_name: str,
) -> None:
    """Register a client with the server.

    Args:
        cli_runner: Click test runner
        config_dir: Path to config directory
        server_url: Server URL
        invitation_token: Invitation token from server
        machine_name: Name for this machine
    """
    from syncagent.client.cli import cli

    with PatchedCLI(config_dir):
        result = cli_runner.invoke(
            cli,
            ["register", "--server", server_url, "--token", invitation_token, "--name", machine_name],
        )
        if result.exit_code != 0:
            raise RuntimeError(f"register failed: {result.output}")


def sync_client(
    cli_runner: CliRunner,
    config_dir: Path,
    password: str = "testpassword",
) -> str:
    """Run sync command for a client.

    Args:
        cli_runner: Click test runner
        config_dir: Path to config directory
        password: Master password

    Returns:
        CLI output
    """
    from syncagent.client.cli import cli

    with PatchedCLI(config_dir):
        result = cli_runner.invoke(cli, ["sync"], input=f"{password}\n")
        if result.exit_code != 0:
            raise RuntimeError(f"sync failed: {result.output}\n{result.exception}")
        return result.output
