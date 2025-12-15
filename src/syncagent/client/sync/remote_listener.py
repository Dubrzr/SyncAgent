"""Remote change listener for real-time sync notifications.

This module provides:
- RemoteChangeListener: WebSocket client that receives push notifications
  for server-side changes (admin deletes, restores, etc.)

Architecture:
    Server ─push─► RemoteChangeListener ─► EventQueue ─► SyncCoordinator
                          │
                   (on reconnect: fetch_remote_changes)

When connected, the listener receives push notifications instantly.
On disconnect/reconnect, it fetches any missed changes since last cursor.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import threading
from typing import TYPE_CHECKING

import websockets
from websockets.exceptions import WebSocketException

from syncagent.client.sync.change_scanner import ChangeScanner, RemoteChanges
from syncagent.client.sync.types import SyncEvent, SyncEventSource, SyncEventType

if TYPE_CHECKING:
    from websockets.asyncio.client import ClientConnection

    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState
    from syncagent.client.sync.queue import EventQueue
    from syncagent.core.config import ServerConfig

logger = logging.getLogger(__name__)


class RemoteChangeListener:
    """WebSocket listener for real-time remote change notifications.

    Connects to the server's WebSocket endpoint and receives push
    notifications when files change (admin delete, restore, etc.).

    On disconnect/reconnect, fetches any missed changes using the
    ChangeScanner to ensure no changes are lost.

    Usage:
        listener = RemoteChangeListener(
            config=server_config,
            http_client=client,
            state=local_state,
            event_queue=queue,
            base_path=sync_folder,
        )
        listener.start()

        # Events are automatically pushed to the queue
        # ...

        listener.stop()
    """

    def __init__(
        self,
        config: ServerConfig,
        http_client: HTTPClient,
        state: LocalSyncState,
        event_queue: EventQueue,
        base_path: str,
        reconnect_delay: float = 5.0,
    ) -> None:
        """Initialize the remote change listener.

        Args:
            config: Server configuration with URL and token.
            http_client: HTTP client for fetching missed changes.
            state: Local sync state for cursor management.
            event_queue: Queue to push events to.
            base_path: Base path for the sync folder.
            reconnect_delay: Delay between reconnection attempts.
        """
        self._config = config
        self._http_client = http_client
        self._state = state
        self._event_queue = event_queue
        self._base_path = base_path
        self._reconnect_delay = reconnect_delay

        # Connection state
        self._ws: ClientConnection | None = None
        self._connected = False
        self._should_run = False

        # Thread and loop
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None
        self._stop_event: asyncio.Event | None = None  # For interruptible sleep

        # Scanner for fetching missed changes
        from pathlib import Path
        self._scanner = ChangeScanner(http_client, state, Path(base_path))

    @property
    def connected(self) -> bool:
        """Check if currently connected."""
        return self._connected

    @property
    def ws_url(self) -> str:
        """Get the WebSocket URL."""
        return self._config.ws_url

    def start(self) -> None:
        """Start the listener in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("RemoteChangeListener already running")
            return

        self._should_run = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="RemoteChangeListener",
            daemon=True,
        )
        self._thread.start()
        logger.info("RemoteChangeListener started")

    def stop(self) -> None:
        """Stop the listener."""
        self._should_run = False

        # Signal stop event to interrupt any sleeps
        if self._loop and self._stop_event:
            asyncio.run_coroutine_threadsafe(
                self._signal_stop(), self._loop
            )

        # Close WebSocket connection
        if self._loop and self._ws:
            with contextlib.suppress(TimeoutError):
                asyncio.run_coroutine_threadsafe(
                    self._close_connection(), self._loop
                ).result(timeout=2.0)

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        logger.info("RemoteChangeListener stopped")

    async def _signal_stop(self) -> None:
        """Signal the stop event to interrupt sleeps."""
        if self._stop_event:
            self._stop_event.set()

    def _run_loop(self) -> None:
        """Run the async event loop in a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._stop_event = asyncio.Event()

        try:
            self._loop.run_until_complete(self._connection_loop())
        finally:
            self._loop.close()
            self._loop = None
            self._stop_event = None

    async def _connection_loop(self) -> None:
        """Main connection loop with automatic reconnection."""
        was_connected = False

        while self._should_run:
            try:
                await self._connect()

                if self._connected:
                    # On (re)connect, fetch any missed changes
                    if was_connected:
                        logger.info("Reconnected, fetching missed changes...")
                    await self._fetch_missed_changes()

                    was_connected = True
                    await self._listen_for_messages()

            except WebSocketException as e:
                if was_connected:
                    logger.warning("RemoteChangeListener disconnected: %s", e)
                logger.debug("WebSocket error: %s", e)
            except (ConnectionRefusedError, OSError) as e:
                if was_connected:
                    logger.warning("RemoteChangeListener connection lost")
                logger.debug("Connection error: %s", e)
            except Exception as e:
                logger.warning("RemoteChangeListener error: %s", e)
                logger.debug("Full traceback:", exc_info=True)

            if not self._should_run:
                break

            self._connected = False

            logger.info(
                "RemoteChangeListener reconnecting in %.0fs...",
                self._reconnect_delay,
            )
            # Use interruptible sleep - will wake on stop signal
            try:
                await asyncio.wait_for(
                    self._stop_event.wait(),  # type: ignore[union-attr]
                    timeout=self._reconnect_delay,
                )
                # If we get here, stop was signaled
                break
            except TimeoutError:
                # Normal timeout, continue reconnect loop
                pass

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        ssl_context: ssl.SSLContext | None = None
        if self.ws_url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            if not self._config.verify_ssl:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

        self._ws = await websockets.connect(
            self.ws_url,
            ssl=ssl_context,
            open_timeout=10,
            close_timeout=5,
        )
        self._connected = True
        logger.info("RemoteChangeListener connected")

    async def _listen_for_messages(self) -> None:
        """Listen for incoming messages from server."""
        while self._should_run and self._ws:
            try:
                message = await asyncio.wait_for(
                    self._ws.recv(),
                    timeout=30.0,  # Check should_run periodically
                )
                if isinstance(message, bytes):
                    message = message.decode("utf-8")
                await self._handle_message(message)

            except TimeoutError:
                continue
            except websockets.ConnectionClosed:
                logger.info("Connection closed by server")
                break

    async def _handle_message(self, message: str) -> None:
        """Handle incoming message from server.

        Supported message types:
        - file_change: Push notification for a file change
          {"type": "file_change", "action": "CREATED|UPDATED|DELETED", "path": "...", "timestamp": "..."}

        Args:
            message: Raw message string.
        """
        try:
            data = json.loads(message)
        except json.JSONDecodeError:
            logger.warning("Invalid message received: %s", message[:100])
            return

        msg_type = data.get("type")

        if msg_type == "file_change":
            action = data.get("action")
            path = data.get("path")

            if not action or not path:
                logger.warning("Invalid file_change message: %s", data)
                return

            logger.info("Received file change: %s %s", action, path)
            self._emit_change_event(action, path)

        # Ignore other message types (status updates, etc.)

    def _emit_change_event(self, action: str, path: str) -> None:
        """Convert a file change notification to a SyncEvent and emit to queue.

        Args:
            action: Change action (CREATED, UPDATED, DELETED).
            path: File path.
        """
        # Map action to event type
        action_to_event = {
            "CREATED": SyncEventType.REMOTE_CREATED,
            "UPDATED": SyncEventType.REMOTE_MODIFIED,
            "DELETED": SyncEventType.REMOTE_DELETED,
        }

        event_type = action_to_event.get(action)
        if not event_type:
            logger.warning("Unknown action: %s", action)
            return

        event = SyncEvent.create(
            event_type=event_type,
            path=path,
            source=SyncEventSource.REMOTE,
        )
        self._event_queue.put(event)
        logger.debug("Emitted remote event: %s %s", action, path)

    async def _fetch_missed_changes(self) -> None:
        """Fetch any changes missed during disconnect.

        Uses the ChangeScanner to get changes since last cursor,
        then emits them to the queue.
        """
        try:
            # Run in executor since scanner methods are synchronous
            loop = asyncio.get_running_loop()
            remote_changes: RemoteChanges = await loop.run_in_executor(
                None, self._scanner.fetch_remote_changes
            )

            # Emit events for each change
            for path in remote_changes.created:
                self._emit_change_event("CREATED", path)

            for path in remote_changes.modified:
                self._emit_change_event("UPDATED", path)

            for path in remote_changes.deleted:
                self._emit_change_event("DELETED", path)

            total = (
                len(remote_changes.created)
                + len(remote_changes.modified)
                + len(remote_changes.deleted)
            )
            if total > 0:
                logger.info("Fetched %d missed changes", total)

        except Exception as e:
            logger.warning("Failed to fetch missed changes: %s", e)

    async def _close_connection(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            with contextlib.suppress(WebSocketException):
                await self._ws.close()
            self._ws = None
        self._connected = False
