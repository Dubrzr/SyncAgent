"""Tests for 'syncagent register' command.

Spec: docs/cli/register.md

Test Scenarios:
---------------

register:
    - [x] Succeeds with valid invitation token
    - [x] Saves server_url, auth_token, machine_name in config
    - [x] Shows server URL and machine name in output
    - [x] Fails if not initialized
    - [x] Fails with invalid token
    - [x] Fails with duplicate machine name
    - [x] Warns if already registered
    - [x] Sanitizes machine name
    - [x] Requires --server option
    - [x] Requires --token option
"""

from __future__ import annotations

import json
from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI, init_client
from tests.integration.conftest import TestServer


class TestRegister:
    """Test 'syncagent register' command."""

    def test_succeeds_with_valid_token(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)
        token = test_server.create_invitation()

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token, "--name", "test-machine"],
            )

            assert result.exit_code == 0, f"register failed: {result.output}"
            assert "registered successfully" in result.output.lower()

    def test_saves_config(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)
        token = test_server.create_invitation()

        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token, "--name", "config-test"],
            )

            config = json.loads((test_config_dir / "config.json").read_text())
            assert config["server_url"] == test_server.url
            assert config["auth_token"] is not None
            assert config["machine_name"] == "config-test"

    def test_shows_server_and_machine_name(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)
        token = test_server.create_invitation()

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token, "--name", "display-test"],
            )

            assert test_server.url in result.output
            assert "display-test" in result.output

    def test_fails_if_not_initialized(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_server: TestServer,
    ) -> None:
        token = test_server.create_invitation()

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token, "--name", "test"],
            )

            assert result.exit_code == 1
            assert "not initialized" in result.output.lower()

    def test_fails_with_invalid_token(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", "invalid-token", "--name", "test"],
            )

            assert result.exit_code == 1
            assert "invalid" in result.output.lower() or "error" in result.output.lower()

    def test_fails_with_duplicate_name(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        # First client
        config_dir_1 = tmp_path / "client1" / ".syncagent"
        config_dir_1.mkdir(parents=True, exist_ok=True)
        sync_folder_1 = tmp_path / "client1" / "sync"
        sync_folder_1.mkdir(parents=True, exist_ok=True)

        init_client(cli_runner, config_dir_1, sync_folder_1)
        token1 = test_server.create_invitation()

        with PatchedCLI(config_dir_1):
            cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token1, "--name", "duplicate"],
            )

        # Second client with same name
        config_dir_2 = tmp_path / "client2" / ".syncagent"
        config_dir_2.mkdir(parents=True, exist_ok=True)
        sync_folder_2 = tmp_path / "client2" / "sync"
        sync_folder_2.mkdir(parents=True, exist_ok=True)

        init_client(cli_runner, config_dir_2, sync_folder_2)
        token2 = test_server.create_invitation()

        with PatchedCLI(config_dir_2):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token2, "--name", "duplicate"],
            )

            assert result.exit_code == 1
            assert "already exists" in result.output.lower()

    def test_warns_if_already_registered(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)

        token1 = test_server.create_invitation()
        with PatchedCLI(test_config_dir):
            cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token1, "--name", "first"],
            )

        token2 = test_server.create_invitation()
        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token2, "--name", "second"],
                input="n\n",
            )

            assert "already registered" in result.output.lower()

    def test_sanitizes_machine_name(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
        test_server: TestServer,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)
        token = test_server.create_invitation()

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", test_server.url, "--token", token, "--name", "Test Machine!@#$"],
            )

            assert result.exit_code == 0
            assert "sanitized" in result.output.lower()

            config = json.loads((test_config_dir / "config.json").read_text())
            # Special chars replaced with underscores: space, !, @, #, $
            assert config["machine_name"] == "Test_Machine____"


class TestRegisterRequiredOptions:
    """Test required options for 'syncagent register'."""

    def test_requires_server_option(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--token", "some-token", "--name", "test"],
            )

            assert result.exit_code != 0
            assert "server" in result.output.lower()

    def test_requires_token_option(
        self,
        cli_runner: CliRunner,
        test_config_dir: Path,
        test_sync_folder: Path,
    ) -> None:
        init_client(cli_runner, test_config_dir, test_sync_folder)

        with PatchedCLI(test_config_dir):
            result = cli_runner.invoke(
                cli,
                ["register", "--server", "http://localhost:8000", "--name", "test"],
            )

            assert result.exit_code != 0
            assert "token" in result.output.lower()
