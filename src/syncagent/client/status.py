"""WebSocket client for status reporting to server.

This module provides:
- StatusReporter: Client-side WebSocket connection for reporting sync status

Architecture:
    Client (StatusReporter) ──ws──► Server (StatusHub) ──ws──► Dashboard
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import ssl
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import websockets
from websockets.exceptions import WebSocketException

from syncagent.core.config import ServerConfig
from syncagent.core.types import SyncState

if TYPE_CHECKING:
    from collections.abc import Callable

    from websockets.asyncio.client import ClientConnection

logger = logging.getLogger(__name__)


@dataclass
class StatusUpdate:
    """Status update to send to server.

    Attributes:
        state: Current sync state.
        files_pending: Number of files waiting in queue.
        uploads_in_progress: Number of files being uploaded.
        downloads_in_progress: Number of files being downloaded.
        upload_speed: Upload speed in bytes/second.
        download_speed: Download speed in bytes/second.
    """

    state: SyncState = SyncState.IDLE
    files_pending: int = 0
    uploads_in_progress: int = 0
    downloads_in_progress: int = 0
    upload_speed: int = 0
    download_speed: int = 0

    def to_message(self) -> dict[str, str | int]:
        """Convert to WebSocket message."""
        return {
            "type": "status",
            "state": self.state.value,
            "files_pending": self.files_pending,
            "uploads_in_progress": self.uploads_in_progress,
            "downloads_in_progress": self.downloads_in_progress,
            "upload_speed": self.upload_speed,
            "download_speed": self.download_speed,
        }


@dataclass
class StatusReporterConfig:
    """Configuration for StatusReporter.

    Attributes:
        heartbeat_interval: Seconds between heartbeats.
        reconnect_min_delay: Minimum delay before reconnection.
        reconnect_max_delay: Maximum delay before reconnection.
        reconnect_backoff: Multiplier for backoff.
    """

    heartbeat_interval: float = 15.0
    reconnect_min_delay: float = 1.0
    reconnect_max_delay: float = 60.0
    reconnect_backoff: float = 2.0


class StatusReporter:
    """WebSocket client for reporting sync status to server.

    Maintains a persistent WebSocket connection with automatic
    reconnection and heartbeat. Status updates are sent when
    the sync state changes.

    Usage:
        server_config = ServerConfig(server_url="http://localhost:8000", token="...")
        reporter = StatusReporter(server_config)
        reporter.start()

        # Report status changes
        reporter.update_status(StatusUpdate(
            state=SyncState.SYNCING,
            files_pending=5,
            uploads_in_progress=2,
        ))

        # Stop when done
        reporter.stop()
    """

    def __init__(
        self,
        config: ServerConfig,
        ws_config: StatusReporterConfig | None = None,
    ) -> None:
        """Initialize the status reporter.

        Args:
            config: Server configuration with URL, token, and settings.
            ws_config: WebSocket-specific configuration (heartbeat, reconnection).
        """
        self._server_config = config
        self._server_url = config.server_url
        self._token = config.token
        self._verify_ssl = config.verify_ssl
        self._ws_config = ws_config or StatusReporterConfig()

        # Connection state
        self._ws: ClientConnection | None = None
        self._connected = False
        self._should_run = False

        # Thread and loop
        self._thread: threading.Thread | None = None
        self._loop: asyncio.AbstractEventLoop | None = None

        # Current status
        self._current_status = StatusUpdate()
        self._status_lock = threading.Lock()

        # Reconnection state
        self._reconnect_delay = self._ws_config.reconnect_min_delay

        # Callbacks
        self._on_connected: Callable[[], None] | None = None
        self._on_disconnected: Callable[[], None] | None = None

    @property
    def connected(self) -> bool:
        """Check if currently connected."""
        return self._connected

    @property
    def ws_url(self) -> str:
        """Get the WebSocket URL."""
        # Convert http(s) to ws(s)
        url = self._server_url
        if url.startswith("https://"):
            url = "wss://" + url[8:]
        elif url.startswith("http://"):
            url = "ws://" + url[7:]
        return f"{url}/ws/client/{self._token}"

    def set_callbacks(
        self,
        on_connected: Callable[[], None] | None = None,
        on_disconnected: Callable[[], None] | None = None,
    ) -> None:
        """Set connection callbacks.

        Args:
            on_connected: Called when connection is established.
            on_disconnected: Called when connection is lost.
        """
        self._on_connected = on_connected
        self._on_disconnected = on_disconnected

    def start(self) -> None:
        """Start the status reporter in a background thread."""
        if self._thread and self._thread.is_alive():
            logger.warning("StatusReporter already running")
            return

        self._should_run = True
        self._thread = threading.Thread(
            target=self._run_loop,
            name="StatusReporter",
            daemon=True,
        )
        self._thread.start()
        logger.info("StatusReporter started")

    def stop(self) -> None:
        """Stop the status reporter."""
        self._should_run = False

        # Close connection if open
        if self._loop and self._ws:
            asyncio.run_coroutine_threadsafe(
                self._close_connection(), self._loop
            ).result(timeout=5.0)

        if self._thread:
            self._thread.join(timeout=5.0)
            self._thread = None

        logger.info("StatusReporter stopped")

    def update_status(self, status: StatusUpdate) -> None:
        """Update the current status.

        The status will be sent to the server if connected.

        Args:
            status: New status to report.
        """
        with self._status_lock:
            self._current_status = status

        # Send immediately if connected
        if self._connected and self._loop:
            future = asyncio.run_coroutine_threadsafe(
                self._send_status(), self._loop
            )
            # Don't block, but log any errors
            future.add_done_callback(self._on_send_complete)

    def report_idle(self) -> None:
        """Report idle state."""
        self.update_status(StatusUpdate(state=SyncState.IDLE))

    def report_syncing(
        self,
        files_pending: int = 0,
        uploads_in_progress: int = 0,
        downloads_in_progress: int = 0,
        upload_speed: int = 0,
        download_speed: int = 0,
    ) -> None:
        """Report syncing state with details.

        Args:
            files_pending: Number of files in queue.
            uploads_in_progress: Number of active uploads.
            downloads_in_progress: Number of active downloads.
            upload_speed: Upload speed in bytes/sec.
            download_speed: Download speed in bytes/sec.
        """
        self.update_status(StatusUpdate(
            state=SyncState.SYNCING,
            files_pending=files_pending,
            uploads_in_progress=uploads_in_progress,
            downloads_in_progress=downloads_in_progress,
            upload_speed=upload_speed,
            download_speed=download_speed,
        ))

    def report_error(self) -> None:
        """Report error state."""
        self.update_status(StatusUpdate(state=SyncState.ERROR))

    def _on_send_complete(self, future: Any) -> None:
        """Callback when send completes."""
        try:
            future.result()
        except Exception as e:
            logger.warning(f"Failed to send status update: {e}")

    def _run_loop(self) -> None:
        """Run the async event loop in a thread."""
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)

        try:
            self._loop.run_until_complete(self._connection_loop())
        finally:
            self._loop.close()
            self._loop = None

    async def _connection_loop(self) -> None:
        """Main connection loop with automatic reconnection."""
        was_connected = False

        while self._should_run:
            try:
                await self._connect()

                if self._connected:
                    was_connected = True
                    self._reconnect_delay = self._ws_config.reconnect_min_delay
                    await self._run_connected()

            except WebSocketException as e:
                if was_connected:
                    logger.warning("StatusReporter disconnected from server")
                    was_connected = False
                logger.debug(f"WebSocket error: {e}")
            except (ConnectionRefusedError, OSError) as e:
                # Network errors - log without traceback
                if was_connected:
                    logger.warning("StatusReporter disconnected from server")
                    was_connected = False
                logger.debug(f"Connection error: {e}")
            except Exception as e:
                # Unexpected errors - log with traceback for debugging
                logger.warning(f"StatusReporter error: {e}")
                logger.debug("Full traceback:", exc_info=True)

            if not self._should_run:
                break

            # Reconnect with backoff
            self._connected = False
            if self._on_disconnected:
                self._on_disconnected()

            logger.info(f"StatusReporter retrying in {self._reconnect_delay:.0f}s...")
            await asyncio.sleep(self._reconnect_delay)

            # Increase delay for next attempt
            self._reconnect_delay = min(
                self._reconnect_delay * self._ws_config.reconnect_backoff,
                self._ws_config.reconnect_max_delay,
            )

    async def _connect(self) -> None:
        """Establish WebSocket connection."""
        # Configure SSL if needed
        ssl_context: ssl.SSLContext | None = None
        if self.ws_url.startswith("wss://"):
            ssl_context = ssl.create_default_context()
            if not self._verify_ssl:
                ssl_context.check_hostname = False
                ssl_context.verify_mode = ssl.CERT_NONE

        self._ws = await websockets.connect(self.ws_url, ssl=ssl_context)
        self._connected = True
        logger.info("StatusReporter connected to server")

        if self._on_connected:
            self._on_connected()

        # Send current status immediately
        await self._send_status()

    async def _run_connected(self) -> None:
        """Run while connected - send heartbeats and handle messages."""
        heartbeat_task = asyncio.create_task(self._heartbeat_loop())

        try:
            # Listen for messages (server might send commands)
            while self._should_run and self._ws:
                try:
                    # Set a timeout so we can check should_run
                    message = await asyncio.wait_for(
                        self._ws.recv(),
                        timeout=1.0,
                    )
                    # Handle any incoming messages if needed
                    if isinstance(message, bytes):
                        message = message.decode("utf-8")
                    await self._handle_message(message)

                except TimeoutError:
                    continue
                except websockets.ConnectionClosed:
                    logger.info("Connection closed by server")
                    break

        finally:
            heartbeat_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await heartbeat_task

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self._should_run and self._connected:
            await asyncio.sleep(self._ws_config.heartbeat_interval)
            if self._connected and self._ws:
                try:
                    await self._ws.send(json.dumps({"type": "heartbeat"}))
                except WebSocketException:
                    break

    async def _send_status(self) -> None:
        """Send current status to server."""
        if not self._connected or not self._ws:
            logger.debug("Cannot send status: not connected")
            return

        with self._status_lock:
            message = self._current_status.to_message()

        try:
            await self._ws.send(json.dumps(message))
            logger.debug(
                f"Status sent: state={message['state']}, "
                f"pending={message.get('files_pending', 0)}, "
                f"up_speed={message.get('upload_speed', 0)}"
            )
        except WebSocketException as e:
            logger.warning(f"Failed to send status: {e}")
            self._connected = False

    async def _handle_message(self, message: str) -> None:
        """Handle incoming message from server.

        Currently just logs, but could be extended for server commands.

        Args:
            message: Raw message string.
        """
        try:
            data = json.loads(message)
            msg_type = data.get("type")
            logger.debug(f"Received message: {msg_type}")
        except json.JSONDecodeError:
            logger.warning(f"Invalid message received: {message[:100]}")

    async def _close_connection(self) -> None:
        """Close the WebSocket connection."""
        if self._ws:
            with contextlib.suppress(WebSocketException):
                await self._ws.close()
            self._ws = None
        self._connected = False
