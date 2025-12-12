"""Tests for WebSocket status hub."""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from starlette.websockets import WebSocketState

from syncagent.core.types import SyncState
from syncagent.server.database import Database
from syncagent.server.ws import (
    MachineStatus,
    StatusHub,
    get_hub,
    set_hub,
)


class TestSyncState:
    """Tests for SyncState enum."""

    def test_sync_state_values(self) -> None:
        """Should have correct string values."""
        assert SyncState.IDLE.value == "idle"
        assert SyncState.SYNCING.value == "syncing"
        assert SyncState.ERROR.value == "error"
        assert SyncState.OFFLINE.value == "offline"


class TestMachineStatus:
    """Tests for MachineStatus dataclass."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        status = MachineStatus(machine_id=1, machine_name="test-machine")
        assert status.machine_id == 1
        assert status.machine_name == "test-machine"
        assert status.state == SyncState.OFFLINE
        assert status.files_pending == 0
        assert status.uploads_in_progress == 0
        assert status.downloads_in_progress == 0
        assert status.upload_speed == 0
        assert status.download_speed == 0
        assert status.last_update is not None

    def test_to_dict(self) -> None:
        """Should convert to JSON-serializable dict."""
        now = datetime.now(UTC)
        status = MachineStatus(
            machine_id=1,
            machine_name="test-machine",
            state=SyncState.SYNCING,
            files_pending=5,
            uploads_in_progress=2,
            downloads_in_progress=1,
            upload_speed=1000,
            download_speed=2000,
            last_update=now,
        )
        d = status.to_dict()
        assert d["machine_id"] == 1
        assert d["machine_name"] == "test-machine"
        assert d["state"] == "syncing"
        assert d["files_pending"] == 5
        assert d["uploads_in_progress"] == 2
        assert d["downloads_in_progress"] == 1
        assert d["upload_speed"] == 1000
        assert d["download_speed"] == 2000
        assert d["last_update"] == now.isoformat()


class TestStatusHub:
    """Tests for StatusHub class."""

    @pytest.fixture
    def hub(self) -> StatusHub:
        """Create a fresh StatusHub."""
        return StatusHub(offline_timeout_seconds=30)

    @pytest.fixture
    def mock_ws(self) -> MagicMock:
        """Create a mock WebSocket."""
        ws = MagicMock()
        ws.accept = AsyncMock()
        ws.close = AsyncMock()
        ws.send_text = AsyncMock()
        ws.client_state = WebSocketState.CONNECTED
        return ws

    @pytest.mark.asyncio
    async def test_connect_client(self, hub: StatusHub, mock_ws: MagicMock) -> None:
        """Should register client and set status to IDLE."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        mock_ws.accept.assert_called_once()
        status = await hub.get_status(1)
        assert status is not None
        assert status.machine_id == 1
        assert status.machine_name == "test"
        assert status.state == SyncState.IDLE

    @pytest.mark.asyncio
    async def test_connect_client_replaces_old(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should close old connection when same machine reconnects."""
        old_ws = MagicMock()
        old_ws.accept = AsyncMock()
        old_ws.close = AsyncMock()
        old_ws.client_state = WebSocketState.CONNECTED

        await hub.connect_client(old_ws, machine_id=1, machine_name="test")
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        old_ws.close.assert_called_once()

    @pytest.mark.asyncio
    async def test_disconnect_client(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should mark status as OFFLINE when client disconnects."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")
        await hub.disconnect_client(1)

        status = await hub.get_status(1)
        assert status is not None
        assert status.state == SyncState.OFFLINE

    @pytest.mark.asyncio
    async def test_connect_dashboard(self, hub: StatusHub, mock_ws: MagicMock) -> None:
        """Should register dashboard and send current status."""
        # First add a machine
        client_ws = MagicMock()
        client_ws.accept = AsyncMock()
        client_ws.client_state = WebSocketState.CONNECTED
        await hub.connect_client(client_ws, machine_id=1, machine_name="test")

        # Then connect dashboard
        await hub.connect_dashboard(mock_ws)

        mock_ws.accept.assert_called_once()
        # Should have sent all_status message
        mock_ws.send_text.assert_called()
        call_args = mock_ws.send_text.call_args[0][0]
        data = json.loads(call_args)
        assert data["type"] == "all_status"
        assert len(data["machines"]) == 1
        assert data["machines"][0]["machine_id"] == 1

    @pytest.mark.asyncio
    async def test_disconnect_dashboard(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should unregister dashboard."""
        await hub.connect_dashboard(mock_ws)
        await hub.disconnect_dashboard(mock_ws)
        # Just verify no error occurs

    @pytest.mark.asyncio
    async def test_update_status(self, hub: StatusHub, mock_ws: MagicMock) -> None:
        """Should update machine status."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        await hub.update_status(
            machine_id=1,
            state=SyncState.SYNCING,
            files_pending=10,
            uploads_in_progress=3,
            downloads_in_progress=2,
            upload_speed=5000,
            download_speed=8000,
        )

        status = await hub.get_status(1)
        assert status is not None
        assert status.state == SyncState.SYNCING
        assert status.files_pending == 10
        assert status.uploads_in_progress == 3
        assert status.downloads_in_progress == 2
        assert status.upload_speed == 5000
        assert status.download_speed == 8000

    @pytest.mark.asyncio
    async def test_update_status_partial(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should update only specified fields."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        await hub.update_status(machine_id=1, files_pending=5)
        status = await hub.get_status(1)
        assert status is not None
        assert status.files_pending == 5
        assert status.state == SyncState.IDLE  # Not changed

        await hub.update_status(machine_id=1, state=SyncState.ERROR)
        status = await hub.get_status(1)
        assert status is not None
        assert status.files_pending == 5  # Not changed
        assert status.state == SyncState.ERROR

    @pytest.mark.asyncio
    async def test_update_status_unknown_machine(self, hub: StatusHub) -> None:
        """Should log warning for unknown machine."""
        # Should not raise error
        await hub.update_status(machine_id=999, state=SyncState.SYNCING)

    @pytest.mark.asyncio
    async def test_broadcast_to_dashboards(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should broadcast status update to all dashboards."""
        # Connect client
        client_ws = MagicMock()
        client_ws.accept = AsyncMock()
        client_ws.client_state = WebSocketState.CONNECTED
        await hub.connect_client(client_ws, machine_id=1, machine_name="test")

        # Connect two dashboards
        dash1 = MagicMock()
        dash1.accept = AsyncMock()
        dash1.send_text = AsyncMock()
        dash1.client_state = WebSocketState.CONNECTED

        dash2 = MagicMock()
        dash2.accept = AsyncMock()
        dash2.send_text = AsyncMock()
        dash2.client_state = WebSocketState.CONNECTED

        await hub.connect_dashboard(dash1)
        await hub.connect_dashboard(dash2)

        # Clear calls from connect
        dash1.send_text.reset_mock()
        dash2.send_text.reset_mock()

        # Update status
        await hub.update_status(machine_id=1, state=SyncState.SYNCING)

        # Both dashboards should receive update
        dash1.send_text.assert_called()
        dash2.send_text.assert_called()

        data1 = json.loads(dash1.send_text.call_args[0][0])
        assert data1["type"] == "status_update"
        assert data1["machine"]["state"] == "syncing"

    @pytest.mark.asyncio
    async def test_handle_client_message_status(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should handle status message from client."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        await hub.handle_client_message(
            1,
            {
                "type": "status",
                "state": "syncing",
                "files_pending": 3,
                "uploads_in_progress": 1,
                "downloads_in_progress": 2,
            },
        )

        status = await hub.get_status(1)
        assert status is not None
        assert status.state == SyncState.SYNCING
        assert status.files_pending == 3
        assert status.uploads_in_progress == 1
        assert status.downloads_in_progress == 2

    @pytest.mark.asyncio
    async def test_handle_client_message_heartbeat(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should update last_update on heartbeat."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        old_status = await hub.get_status(1)
        assert old_status is not None
        old_update = old_status.last_update

        await asyncio.sleep(0.01)  # Small delay
        await hub.handle_client_message(1, {"type": "heartbeat"})

        new_status = await hub.get_status(1)
        assert new_status is not None
        assert new_status.last_update > old_update

    @pytest.mark.asyncio
    async def test_handle_client_message_unknown_type(
        self, hub: StatusHub, mock_ws: MagicMock
    ) -> None:
        """Should log warning for unknown message type."""
        await hub.connect_client(mock_ws, machine_id=1, machine_name="test")

        # Should not raise error
        await hub.handle_client_message(1, {"type": "unknown"})

    @pytest.mark.asyncio
    async def test_get_all_status(self, hub: StatusHub) -> None:
        """Should return status of all machines."""
        # Connect multiple clients
        for i in range(3):
            ws = MagicMock()
            ws.accept = AsyncMock()
            ws.client_state = WebSocketState.CONNECTED
            await hub.connect_client(ws, machine_id=i, machine_name=f"machine-{i}")

        all_status = await hub.get_all_status()
        assert len(all_status) == 3
        ids = {s.machine_id for s in all_status}
        assert ids == {0, 1, 2}


class TestGlobalHub:
    """Tests for global hub functions."""

    def test_get_hub_creates_singleton(self) -> None:
        """Should create hub if not exists."""
        set_hub(None)  # type: ignore[arg-type]
        hub = get_hub()
        assert hub is not None
        assert isinstance(hub, StatusHub)

    def test_set_hub(self) -> None:
        """Should set custom hub."""
        custom_hub = StatusHub(offline_timeout_seconds=60)
        set_hub(custom_hub)
        assert get_hub() is custom_hub


class TestWebSocketEndpoints:
    """Tests for WebSocket endpoints."""

    @pytest.fixture
    def tmp_db(self, tmp_path: Path) -> Database:
        """Create a temporary database."""
        return Database(tmp_path / "test.db")

    @pytest.fixture
    def machine_with_token(self, tmp_db: Database) -> tuple[int, str]:
        """Create a machine with token."""
        machine = tmp_db.create_machine("test-machine", platform=sys.platform)
        token_str, _ = tmp_db.create_token(machine.id)
        return machine.id, token_str

    @pytest.mark.asyncio
    async def test_client_endpoint_invalid_token(self, tmp_db: Database) -> None:
        """Should close connection for invalid token."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient
        from starlette.websockets import WebSocketDisconnect

        from syncagent.server.ws import router, set_hub

        app = FastAPI()
        app.state.db = tmp_db
        set_hub(StatusHub())
        app.include_router(router)

        client = TestClient(app)
        with pytest.raises(WebSocketDisconnect), client.websocket_connect("/ws/client/invalid-token") as ws:
            ws.receive_json()  # Should disconnect immediately

    @pytest.mark.asyncio
    async def test_client_endpoint_valid_token(
        self, tmp_db: Database, machine_with_token: tuple[int, str]
    ) -> None:
        """Should accept connection with valid token."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from syncagent.server.ws import router, set_hub

        machine_id, token = machine_with_token

        app = FastAPI()
        app.state.db = tmp_db
        hub = StatusHub()
        set_hub(hub)
        app.include_router(router)

        client = TestClient(app)
        with client.websocket_connect(f"/ws/client/{token}") as ws:
            # Send a status update
            ws.send_json({
                "type": "status",
                "state": "syncing",
                "files_pending": 5,
            })
            # Give time for processing
            await asyncio.sleep(0.01)

    @pytest.mark.asyncio
    async def test_dashboard_endpoint(self, tmp_db: Database) -> None:
        """Should accept dashboard connection."""
        from fastapi import FastAPI
        from starlette.testclient import TestClient

        from syncagent.server.ws import router, set_hub

        app = FastAPI()
        app.state.db = tmp_db
        hub = StatusHub()
        set_hub(hub)
        app.include_router(router)

        client = TestClient(app)
        with client.websocket_connect("/ws/dashboard") as ws:
            # Should receive initial all_status
            data = ws.receive_json()
            assert data["type"] == "all_status"
            assert "machines" in data
