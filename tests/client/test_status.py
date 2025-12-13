"""Tests for StatusReporter WebSocket client."""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from syncagent.client.status import (
    StatusReporter,
    StatusReporterConfig,
    StatusUpdate,
)
from syncagent.core.config import ServerConfig
from syncagent.core.types import SyncState


class TestSyncState:
    """Tests for SyncState enum."""

    def test_values(self) -> None:
        """Should have correct string values."""
        assert SyncState.IDLE.value == "idle"
        assert SyncState.SYNCING.value == "syncing"
        assert SyncState.ERROR.value == "error"
        assert SyncState.OFFLINE.value == "offline"


class TestStatusUpdate:
    """Tests for StatusUpdate dataclass."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        status = StatusUpdate()
        assert status.state == SyncState.IDLE
        assert status.files_pending == 0
        assert status.uploads_in_progress == 0
        assert status.downloads_in_progress == 0
        assert status.upload_speed == 0
        assert status.download_speed == 0

    def test_to_message(self) -> None:
        """Should convert to WebSocket message."""
        status = StatusUpdate(
            state=SyncState.SYNCING,
            files_pending=5,
            uploads_in_progress=2,
            downloads_in_progress=1,
            upload_speed=1000,
            download_speed=2000,
        )
        msg = status.to_message()
        assert msg["type"] == "status"
        assert msg["state"] == "syncing"
        assert msg["files_pending"] == 5
        assert msg["uploads_in_progress"] == 2
        assert msg["downloads_in_progress"] == 1
        assert msg["upload_speed"] == 1000
        assert msg["download_speed"] == 2000


class TestStatusReporterConfig:
    """Tests for StatusReporterConfig."""

    def test_default_values(self) -> None:
        """Should have sensible defaults."""
        config = StatusReporterConfig()
        assert config.heartbeat_interval == 15.0
        assert config.reconnect_min_delay == 1.0
        assert config.reconnect_max_delay == 60.0
        assert config.reconnect_backoff == 2.0


class TestStatusReporter:
    """Tests for StatusReporter class."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a server config."""
        return ServerConfig(server_url="http://localhost:8000", token="token123")

    def test_ws_url_http(self, config: ServerConfig) -> None:
        """Should convert http to ws."""
        reporter = StatusReporter(config)
        assert reporter.ws_url == "ws://localhost:8000/ws/client/token123"

    def test_ws_url_https(self) -> None:
        """Should convert https to wss."""
        config = ServerConfig(server_url="https://example.com", token="token123")
        reporter = StatusReporter(config)
        assert reporter.ws_url == "wss://example.com/ws/client/token123"

    def test_ws_url_trailing_slash(self) -> None:
        """Should handle trailing slash."""
        config = ServerConfig(server_url="http://localhost:8000/", token="token123")
        reporter = StatusReporter(config)
        assert reporter.ws_url == "ws://localhost:8000/ws/client/token123"

    def test_not_connected_initially(self, config: ServerConfig) -> None:
        """Should not be connected initially."""
        reporter = StatusReporter(config)
        assert not reporter.connected

    def test_update_status(self, config: ServerConfig) -> None:
        """Should update current status."""
        reporter = StatusReporter(config)
        status = StatusUpdate(
            state=SyncState.SYNCING,
            files_pending=5,
        )
        reporter.update_status(status)
        # Status should be stored (internal)
        assert reporter._current_status.state == SyncState.SYNCING
        assert reporter._current_status.files_pending == 5

    def test_set_callbacks(self, config: ServerConfig) -> None:
        """Should store callbacks."""
        reporter = StatusReporter(config)
        on_connected = MagicMock()
        on_disconnected = MagicMock()
        reporter.set_callbacks(
            on_connected=on_connected,
            on_disconnected=on_disconnected,
        )
        assert reporter._on_connected is on_connected
        assert reporter._on_disconnected is on_disconnected


class TestStatusReporterConnection:
    """Tests for StatusReporter connection handling."""

    @pytest.fixture
    def reporter(self) -> StatusReporter:
        """Create a reporter instance."""
        config = ServerConfig(server_url="http://localhost:8000", token="test-token")
        return StatusReporter(
            config,
            ws_config=StatusReporterConfig(
                heartbeat_interval=1.0,
                reconnect_min_delay=0.1,
                reconnect_max_delay=1.0,
            ),
        )

    @pytest.mark.asyncio
    async def test_connect_success(self, reporter: StatusReporter) -> None:
        """Should connect and send initial status."""
        mock_ws = AsyncMock()
        mock_ws.recv = AsyncMock(side_effect=asyncio.CancelledError)

        async def mock_connect(*args: Any, **kwargs: Any) -> AsyncMock:
            return mock_ws

        with patch(
            "syncagent.client.status.websockets.connect",
            side_effect=mock_connect,
        ):
            await reporter._connect()

            assert reporter.connected
            mock_ws.send.assert_called()  # Initial status sent

    @pytest.mark.asyncio
    async def test_connect_failure(self, reporter: StatusReporter) -> None:
        """Should handle connection failure."""
        from websockets.exceptions import WebSocketException

        async def mock_connect(*args: Any, **kwargs: Any) -> None:
            raise WebSocketException("Connection failed")

        with patch(
            "syncagent.client.status.websockets.connect",
            side_effect=mock_connect,
        ):
            with pytest.raises(WebSocketException):
                await reporter._connect()

            assert not reporter.connected

    @pytest.mark.asyncio
    async def test_send_status(self, reporter: StatusReporter) -> None:
        """Should send status message."""
        mock_ws = AsyncMock()
        reporter._ws = mock_ws
        reporter._connected = True

        reporter._current_status = StatusUpdate(
            state=SyncState.SYNCING,
            files_pending=3,
        )

        await reporter._send_status()

        mock_ws.send.assert_called_once()
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "status"
        assert sent_data["state"] == "syncing"
        assert sent_data["files_pending"] == 3

    @pytest.mark.asyncio
    async def test_heartbeat_loop(self, reporter: StatusReporter) -> None:
        """Should send heartbeats periodically."""
        mock_ws = AsyncMock()
        reporter._ws = mock_ws
        reporter._connected = True
        reporter._should_run = True
        reporter._ws_config.heartbeat_interval = 0.1

        # Run for a short time then stop
        async def stop_after_delay() -> None:
            await asyncio.sleep(0.25)
            reporter._should_run = False

        await asyncio.gather(
            reporter._heartbeat_loop(),
            stop_after_delay(),
        )

        # Should have sent at least one heartbeat
        assert mock_ws.send.call_count >= 1
        sent_data = json.loads(mock_ws.send.call_args[0][0])
        assert sent_data["type"] == "heartbeat"

    @pytest.mark.asyncio
    async def test_handle_message(self, reporter: StatusReporter) -> None:
        """Should handle incoming messages."""
        # Should not raise for valid JSON
        await reporter._handle_message('{"type": "test", "data": 123}')

        # Should not raise for invalid JSON either (just logs warning)
        await reporter._handle_message("not json")

    @pytest.mark.asyncio
    async def test_close_connection(self, reporter: StatusReporter) -> None:
        """Should close connection cleanly."""
        mock_ws = AsyncMock()
        reporter._ws = mock_ws
        reporter._connected = True

        await reporter._close_connection()

        mock_ws.close.assert_called_once()
        assert reporter._ws is None
        assert not reporter.connected


class TestStatusReporterLifecycle:
    """Tests for StatusReporter start/stop lifecycle."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a server config."""
        return ServerConfig(server_url="http://localhost:8000", token="token")

    def test_start_stop(self, config: ServerConfig) -> None:
        """Should start and stop cleanly."""
        reporter = StatusReporter(config)

        # Mock the connection loop to just sleep
        with patch.object(
            reporter, "_connection_loop", new_callable=AsyncMock
        ) as mock_loop:

            async def wait_forever() -> None:
                while reporter._should_run:
                    await asyncio.sleep(0.1)

            mock_loop.side_effect = wait_forever

            reporter.start()
            time.sleep(0.1)  # Give thread time to start

            assert reporter._thread is not None
            assert reporter._thread.is_alive()

            reporter.stop()

            assert not reporter._should_run

    def test_double_start(self, config: ServerConfig) -> None:
        """Should handle double start gracefully."""
        reporter = StatusReporter(config)

        with patch.object(
            reporter, "_connection_loop", new_callable=AsyncMock
        ) as mock_loop:

            async def wait_forever() -> None:
                while reporter._should_run:
                    await asyncio.sleep(0.1)

            mock_loop.side_effect = wait_forever

            reporter.start()
            reporter.start()  # Second start should be ignored

            # Only one thread should be created
            reporter.stop()
