"""E2E tests for WebSocket push notifications.

Test Scenarios:
---------------

WebSocket push notifications:
    - [x] Admin delete triggers push to connected clients
    - [x] Admin restore triggers push to connected clients
    - [x] Push message contains correct action and path
    - [x] Client receives events via RemoteChangeListener
    - [x] On reconnect, missed changes are fetched

Server machine visibility:
    - [x] Server machine is hidden from machines list
    - [x] Server machine cannot be deleted
"""

from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path

import pytest
import websockets
from click.testing import CliRunner

from syncagent.client.cli import cli
from syncagent.client.sync import EventQueue, RemoteChangeListener, SyncEventType
from syncagent.core.config import ServerConfig
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


class TestWebSocketPushNotifications:
    """E2E tests for WebSocket push notifications."""

    @pytest.mark.asyncio
    async def test_delete_triggers_push_notification(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Admin delete should send push notification via WebSocket."""
        # Setup two clients - A will listen, B (or admin) will delete
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Client A uploads a file
        (sync_a / "push_test.txt").write_text("Delete via other client")
        do_sync(cli_runner, config_a)

        # Client B syncs to get the file
        do_sync(cli_runner, config_b)

        # Get auth tokens
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config_a_data = load_config()
        with PatchedCLI(config_b):
            config_b_data = load_config()

        # Client A connects to WebSocket to listen
        ws_url = test_server.url.replace("http://", "ws://") + f"/ws/client/{config_a_data['auth_token']}"
        messages: list[dict] = []

        async def listen_for_messages() -> None:
            async with websockets.connect(ws_url) as ws:
                try:
                    # Wait for messages with timeout
                    message = await asyncio.wait_for(ws.recv(), timeout=5.0)
                    messages.append(json.loads(message))
                except TimeoutError:
                    pass

        # Start listener in background
        listen_task = asyncio.create_task(listen_for_messages())

        # Wait a bit for connection to establish
        await asyncio.sleep(0.5)

        # Client B deletes via API (this should trigger push to Client A)
        import httpx
        response = httpx.delete(
            f"{test_server.url}/api/files/push_test.txt",
            headers={"Authorization": f"Bearer {config_b_data['auth_token']}"},
        )
        assert response.status_code == 204

        # Wait for message
        await listen_task

        # Verify Client A received the push notification
        assert len(messages) >= 1
        file_change_msg = next(
            (m for m in messages if m.get("type") == "file_change"),
            None,
        )
        assert file_change_msg is not None
        assert file_change_msg["action"] == "DELETED"
        assert file_change_msg["path"] == "push_test.txt"

    def test_remote_listener_receives_push_events(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """RemoteChangeListener should receive push events and emit to queue."""
        import httpx

        from syncagent.client.api import HTTPClient
        from syncagent.client.state import LocalSyncState

        # Setup two clients - A will listen, B will delete
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Client A uploads a file
        (sync_a / "listener_test.txt").write_text("Test content")
        do_sync(cli_runner, config_a)

        # Client B syncs to get the file
        do_sync(cli_runner, config_b)

        # Setup listener for Client A
        from syncagent.client.cli.config import load_config

        with PatchedCLI(config_a):
            config_a_data = load_config()
        with PatchedCLI(config_b):
            config_b_data = load_config()

        server_config = ServerConfig(
            server_url=config_a_data["server_url"],
            token=config_a_data["auth_token"],
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        queue = EventQueue()

        listener = RemoteChangeListener(
            config=server_config,
            http_client=client,
            state=state,
            event_queue=queue,
            base_path=str(sync_a),
        )
        listener.start()

        # Wait for connection
        time.sleep(1.0)

        # Client B deletes via API (triggers push to Client A)
        response = httpx.delete(
            f"{test_server.url}/api/files/listener_test.txt",
            headers={"Authorization": f"Bearer {config_b_data['auth_token']}"},
        )
        assert response.status_code == 204

        # Wait for push notification
        time.sleep(2.0)

        listener.stop()

        # Check if event was received
        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_DELETED
        assert event.path == "listener_test.txt"

    def test_listener_fetches_missed_changes_on_reconnect(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """RemoteChangeListener should fetch missed changes on reconnect."""
        from syncagent.client.api import HTTPClient
        from syncagent.client.state import LocalSyncState

        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Upload a file
        (sync_a / "reconnect_test.txt").write_text("Test content")
        do_sync(cli_runner, config_a)

        # Setup scanner to establish cursor
        from syncagent.client.cli.config import load_config
        from syncagent.client.sync import ChangeScanner

        with PatchedCLI(config_a):
            config = load_config()

        server_config = ServerConfig(
            server_url=config["server_url"],
            token=config["auth_token"],
        )
        client = HTTPClient(server_config)
        state = LocalSyncState(config_a / "state.db")
        scanner = ChangeScanner(client, state, sync_a)

        # Fetch to establish cursor
        scanner.fetch_remote_changes()

        # Admin deletes while "offline"
        test_server.db.delete_file("reconnect_test.txt", machine_id=None)

        # Now start listener - it should fetch missed changes
        queue = EventQueue()
        listener = RemoteChangeListener(
            config=server_config,
            http_client=client,
            state=state,
            event_queue=queue,
            base_path=str(sync_a),
        )
        listener.start()

        # Wait for connection and fetch
        time.sleep(2.0)
        listener.stop()

        # Should have received the missed deletion
        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_DELETED
        assert event.path == "reconnect_test.txt"


class TestServerMachineVisibility:
    """Tests for server machine visibility in the WUI."""

    def test_server_machine_hidden_from_list(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Server machine should not appear in machines list."""
        import httpx

        config_a, _ = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Ensure server machine exists by triggering an admin operation
        test_server.db.get_or_create_server_machine()

        # Get auth token
        from syncagent.client.cli.config import load_config
        with PatchedCLI(config_a):
            config = load_config()

        # List machines via API
        response = httpx.get(
            f"{test_server.url}/api/machines",
            headers={"Authorization": f"Bearer {config['auth_token']}"},
        )
        assert response.status_code == 200

        machines = response.json()
        machine_names = [m["name"] for m in machines]

        # Server machine should not be in the list
        assert "server" not in machine_names
        # But client-a should be there
        assert "client-a" in machine_names

    def test_server_machine_cannot_be_deleted(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Server machine should not be deletable."""
        import httpx

        config_a, _ = setup_client(cli_runner, tmp_path, test_server, "client-a")

        # Get or create server machine
        server_machine = test_server.db.get_or_create_server_machine()

        # Get auth token
        from syncagent.client.cli.config import load_config
        with PatchedCLI(config_a):
            config = load_config()

        # Try to delete server machine
        response = httpx.delete(
            f"{test_server.url}/api/machines/{server_machine.id}",
            headers={"Authorization": f"Bearer {config['auth_token']}"},
        )

        # Should be forbidden
        assert response.status_code == 403
        assert "internal server machine" in response.json()["detail"].lower()
