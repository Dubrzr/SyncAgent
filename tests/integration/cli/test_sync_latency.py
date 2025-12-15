"""E2E tests for sync latency (<5s requirement from R9).

Test Scenarios:
---------------

Sync latency (R9 requirement):
    - [x] Small file sync completes in <5s after WebSocket push notification
    - [x] Push notification received in <2s
    - [x] End-to-end sync (upload + push + download) completes in <5s
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time
from pathlib import Path

import pytest
import websockets
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


class TestSyncLatency:
    """E2E tests for sync latency (R9: <5s requirement)."""

    @pytest.mark.asyncio
    async def test_websocket_push_notification_latency_under_2s(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """WebSocket push notification should be received in <2s.

        Note: Notifications exclude the machine that made the change,
        so we need two clients: A uploads, B listens, A deletes → B receives notification.
        """
        # Setup two clients with same encryption key
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "latency-a")
        config_b, sync_b = setup_client(
            cli_runner, tmp_path, test_server, "latency-b", import_key_from=config_a
        )

        # Upload a file from client A
        (sync_a / "latency_test.txt").write_text("Small test file")
        do_sync(cli_runner, config_a)

        # Sync to client B so it knows about the file
        do_sync(cli_runner, config_b)

        # Get auth tokens for both clients
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config_a_data = load_config()

        with PatchedCLI(config_b):
            config_b_data = load_config()

        # Connect client B to WebSocket (B will listen for notifications)
        ws_url_b = test_server.url.replace("http://", "ws://") + f"/ws/client/{config_b_data['auth_token']}"
        notification_received = asyncio.Event()

        async def listen_for_notification() -> None:
            async with websockets.connect(ws_url_b) as ws:
                # Wait for the file_change notification
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    data = json.loads(msg)
                    if data.get("type") == "file_change":
                        notification_received.set()
                except TimeoutError:
                    pass

        # Start listener for client B
        listener = asyncio.create_task(listen_for_notification())

        # Give WebSocket time to connect
        await asyncio.sleep(0.3)

        # Trigger a file change via API from client A (delete)
        # Client B should receive the notification (A is excluded)
        import httpx

        start_time = time.perf_counter()
        async with httpx.AsyncClient() as client:
            await client.delete(
                f"{test_server.url}/api/files/latency_test.txt",
                headers={"Authorization": f"Bearer {config_a_data['auth_token']}"},
            )

        # Wait for notification on client B
        try:
            await asyncio.wait_for(notification_received.wait(), timeout=2.0)
            total_latency = (time.perf_counter() - start_time) * 1000
            assert total_latency < 2000, f"Push notification took {total_latency:.0f}ms, expected <2000ms"
        finally:
            listener.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await listener

    @pytest.mark.asyncio
    async def test_small_file_sync_under_5s(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Small file sync should complete in <5s end-to-end."""
        # Setup two clients with same encryption key
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "speed-a")
        config_b, sync_b = setup_client(
            cli_runner, tmp_path, test_server, "speed-b", import_key_from=config_a
        )

        # Initial sync for client B
        do_sync(cli_runner, config_b)

        # Create small file on client A
        test_content = "Small file for latency test - 100 bytes of content for testing sync speed."
        (sync_a / "speed_test.txt").write_text(test_content)

        # Measure total sync time
        start = time.perf_counter()

        # Upload from A
        do_sync(cli_runner, config_a)

        # Download to B
        do_sync(cli_runner, config_b)

        elapsed = time.perf_counter() - start

        # Verify file was synced
        assert (sync_b / "speed_test.txt").exists()
        assert (sync_b / "speed_test.txt").read_text() == test_content

        # Assert <5s (with some margin for CI environments)
        assert elapsed < 5.0, f"Sync took {elapsed:.2f}s, expected <5s"

    @pytest.mark.asyncio
    async def test_multiple_small_files_sync_under_5s(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Multiple small files should sync in <5s total."""
        # Setup two clients
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "multi-a")
        config_b, sync_b = setup_client(
            cli_runner, tmp_path, test_server, "multi-b", import_key_from=config_a
        )

        # Initial sync for client B
        do_sync(cli_runner, config_b)

        # Create 5 small files on client A
        for i in range(5):
            (sync_a / f"multi_test_{i}.txt").write_text(f"Content for file {i}")

        # Measure total sync time
        start = time.perf_counter()

        # Upload from A
        do_sync(cli_runner, config_a)

        # Download to B
        do_sync(cli_runner, config_b)

        elapsed = time.perf_counter() - start

        # Verify all files were synced
        for i in range(5):
            assert (sync_b / f"multi_test_{i}.txt").exists()
            assert (sync_b / f"multi_test_{i}.txt").read_text() == f"Content for file {i}"

        # Assert <5s
        assert elapsed < 5.0, f"Sync of 5 files took {elapsed:.2f}s, expected <5s"
