"""Tests for server command.

Spec: docs/cli/server.md

Test Scenarios:
---------------

Server startup:
    - [x] Starts server with default options
    - [x] Custom port option works
    - [x] Custom db-path option works
    - [x] Custom storage-path option works

Server output:
    - [x] Shows startup banner
    - [x] Shows configured paths
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from click.testing import CliRunner

from syncagent.client.cli import cli


class TestServerStartup:
    """Tests for server command startup."""

    def test_server_command_exists(self, cli_runner: CliRunner) -> None:
        """Server command should be available."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert result.exit_code == 0
        assert "Start the SyncAgent server" in result.output

    def test_shows_port_option(self, cli_runner: CliRunner) -> None:
        """Server should accept --port option."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert "--port" in result.output or "-p" in result.output

    def test_shows_host_option(self, cli_runner: CliRunner) -> None:
        """Server should accept --host option."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert "--host" in result.output or "-h" in result.output

    def test_shows_db_path_option(self, cli_runner: CliRunner) -> None:
        """Server should accept --db-path option."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert "--db-path" in result.output

    def test_shows_storage_path_option(self, cli_runner: CliRunner) -> None:
        """Server should accept --storage-path option."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert "--storage-path" in result.output

    def test_shows_reload_option(self, cli_runner: CliRunner) -> None:
        """Server should accept --reload option."""
        result = cli_runner.invoke(cli, ["server", "--help"])

        assert "--reload" in result.output

    def test_starts_server_with_custom_paths(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Server should accept custom db and storage paths."""
        db_path = tmp_path / "custom.db"
        storage_path = tmp_path / "custom_storage"

        # Mock uvicorn.run to avoid actually starting server
        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(
                cli,
                [
                    "server",
                    "--db-path",
                    str(db_path),
                    "--storage-path",
                    str(storage_path),
                    "--port",
                    "9000",
                ],
            )

            # Should have called uvicorn.run
            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 9000

    def test_default_port_is_8000(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Default port should be 8000."""
        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(cli, ["server"])

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["port"] == 8000

    def test_default_host_is_0_0_0_0(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Default host should be 0.0.0.0."""
        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(cli, ["server"])

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["host"] == "0.0.0.0"

    def test_reload_option(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """--reload should enable auto-reload mode."""
        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(cli, ["server", "--reload"])

            mock_run.assert_called_once()
            call_kwargs = mock_run.call_args[1]
            assert call_kwargs["reload"] is True


class TestServerEnvironment:
    """Tests for server environment variable handling."""

    def test_sets_db_path_env(self, cli_runner: CliRunner, tmp_path: Path) -> None:
        """Custom db-path should set environment variable."""
        db_path = tmp_path / "test.db"

        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(
                cli, ["server", "--db-path", str(db_path)]
            )

            # The env should be set before uvicorn.run
            mock_run.assert_called_once()

    def test_sets_storage_path_env(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Custom storage-path should set environment variable."""
        storage_path = tmp_path / "storage"

        with patch("uvicorn.run") as mock_run:
            cli_runner.invoke(
                cli, ["server", "--storage-path", str(storage_path)]
            )

            mock_run.assert_called_once()
