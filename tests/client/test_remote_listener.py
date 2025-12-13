"""Tests for RemoteChangeListener."""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from syncagent.client.sync.queue import EventQueue
from syncagent.client.sync.remote_listener import RemoteChangeListener
from syncagent.client.sync.types import SyncEventSource, SyncEventType
from syncagent.core.config import ServerConfig

if TYPE_CHECKING:
    pass


class TestRemoteChangeListenerInit:
    """Tests for RemoteChangeListener initialization."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a test ServerConfig."""
        return ServerConfig(server_url="http://localhost:8000", token="test-token")

    @pytest.fixture
    def mock_http_client(self) -> MagicMock:
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create a mock local sync state."""
        state = MagicMock()
        state.get_last_change_cursor.return_value = None
        return state

    @pytest.fixture
    def queue(self) -> EventQueue:
        """Create an event queue."""
        return EventQueue()

    def test_ws_url_uses_config(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """ws_url should use ServerConfig.ws_url."""
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )
        assert listener.ws_url == "ws://localhost:8000/ws/client/test-token"

    def test_ws_url_https(
        self,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """ws_url should handle HTTPS URLs."""
        config = ServerConfig(server_url="https://example.com", token="token")
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )
        assert listener.ws_url == "wss://example.com/ws/client/token"

    def test_not_connected_initially(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """Listener should not be connected initially."""
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )
        assert not listener.connected


class TestRemoteChangeListenerEvents:
    """Tests for event emission from RemoteChangeListener."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a test ServerConfig."""
        return ServerConfig(server_url="http://localhost:8000", token="test-token")

    @pytest.fixture
    def mock_http_client(self) -> MagicMock:
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create a mock local sync state."""
        state = MagicMock()
        state.get_last_change_cursor.return_value = None
        return state

    @pytest.fixture
    def queue(self) -> EventQueue:
        """Create an event queue."""
        return EventQueue()

    @pytest.fixture
    def listener(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> RemoteChangeListener:
        """Create a listener for testing."""
        return RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )

    def test_emit_created_event(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """CREATED action should emit REMOTE_CREATED event."""
        listener._emit_change_event("CREATED", "test/file.txt")

        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_CREATED
        assert event.path == "test/file.txt"
        assert event.source == SyncEventSource.REMOTE

    def test_emit_updated_event(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """UPDATED action should emit REMOTE_MODIFIED event."""
        listener._emit_change_event("UPDATED", "test/file.txt")

        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_MODIFIED
        assert event.path == "test/file.txt"

    def test_emit_deleted_event(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """DELETED action should emit REMOTE_DELETED event."""
        listener._emit_change_event("DELETED", "test/file.txt")

        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_DELETED
        assert event.path == "test/file.txt"

    def test_emit_unknown_action_ignored(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """Unknown actions should be ignored."""
        listener._emit_change_event("UNKNOWN", "test/file.txt")

        event = queue.get(timeout=0.1)
        assert event is None


class TestRemoteChangeListenerMessageHandling:
    """Tests for message handling in RemoteChangeListener."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a test ServerConfig."""
        return ServerConfig(server_url="http://localhost:8000", token="test-token")

    @pytest.fixture
    def mock_http_client(self) -> MagicMock:
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create a mock local sync state."""
        state = MagicMock()
        state.get_last_change_cursor.return_value = None
        return state

    @pytest.fixture
    def queue(self) -> EventQueue:
        """Create an event queue."""
        return EventQueue()

    @pytest.fixture
    def listener(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> RemoteChangeListener:
        """Create a listener for testing."""
        return RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )

    @pytest.mark.asyncio
    async def test_handle_file_change_message(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """file_change message should emit an event."""
        message = json.dumps({
            "type": "file_change",
            "action": "DELETED",
            "path": "deleted/file.txt",
            "timestamp": "2025-01-01T00:00:00Z",
        })

        await listener._handle_message(message)

        event = queue.get(timeout=1.0)
        assert event is not None
        assert event.event_type == SyncEventType.REMOTE_DELETED
        assert event.path == "deleted/file.txt"

    @pytest.mark.asyncio
    async def test_handle_invalid_json(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """Invalid JSON should be ignored."""
        await listener._handle_message("not valid json {{{")

        event = queue.get(timeout=0.1)
        assert event is None

    @pytest.mark.asyncio
    async def test_handle_non_file_change_message(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """Non file_change messages should be ignored."""
        message = json.dumps({
            "type": "status_update",
            "machine": {},
        })

        await listener._handle_message(message)

        event = queue.get(timeout=0.1)
        assert event is None

    @pytest.mark.asyncio
    async def test_handle_incomplete_file_change(
        self,
        listener: RemoteChangeListener,
        queue: EventQueue,
    ) -> None:
        """file_change without required fields should be ignored."""
        message = json.dumps({
            "type": "file_change",
            # Missing action and path
        })

        await listener._handle_message(message)

        event = queue.get(timeout=0.1)
        assert event is None


class TestRemoteChangeListenerLifecycle:
    """Tests for start/stop lifecycle of RemoteChangeListener."""

    @pytest.fixture
    def config(self) -> ServerConfig:
        """Create a test ServerConfig."""
        return ServerConfig(server_url="http://localhost:8000", token="test-token")

    @pytest.fixture
    def mock_http_client(self) -> MagicMock:
        """Create a mock HTTP client."""
        return MagicMock()

    @pytest.fixture
    def mock_state(self) -> MagicMock:
        """Create a mock local sync state."""
        state = MagicMock()
        state.get_last_change_cursor.return_value = None
        return state

    @pytest.fixture
    def queue(self) -> EventQueue:
        """Create an event queue."""
        return EventQueue()

    def test_start_creates_thread(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """start() should create a background thread."""
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )

        # Patch the connection to fail immediately
        with patch.object(listener, "_connect", side_effect=ConnectionRefusedError):
            listener.start()
            time.sleep(0.1)  # Give thread time to start

            assert listener._thread is not None
            assert listener._thread.is_alive()

            listener.stop()

    def test_double_start_does_nothing(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """Calling start() twice should not create duplicate threads."""
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )

        with patch.object(listener, "_connect", side_effect=ConnectionRefusedError):
            listener.start()
            first_thread = listener._thread

            listener.start()  # Second call
            assert listener._thread is first_thread

            listener.stop()

    def test_stop_cleans_up(
        self,
        config: ServerConfig,
        mock_http_client: MagicMock,
        mock_state: MagicMock,
        queue: EventQueue,
        tmp_path: Path,
    ) -> None:
        """stop() should clean up thread and connection."""
        listener = RemoteChangeListener(
            config=config,
            http_client=mock_http_client,
            state=mock_state,
            event_queue=queue,
            base_path=str(tmp_path),
        )

        with patch.object(listener, "_connect", side_effect=ConnectionRefusedError):
            listener.start()
            time.sleep(0.1)

            listener.stop()

            assert listener._thread is None
            assert not listener._should_run
