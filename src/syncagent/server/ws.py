"""WebSocket hub for real-time status updates.

This module provides:
- StatusHub: Central hub for managing WebSocket connections
- Machine status broadcasting to dashboard

Architecture:
    Client (sync daemon) ──ws──► StatusHub ──ws──► Dashboard (browser)
                                    │
                              (in-memory status)
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from starlette.websockets import WebSocketState

from syncagent.core.types import SyncState

if TYPE_CHECKING:
    from syncagent.server.database import Database

logger = logging.getLogger(__name__)


@dataclass
class MachineStatus:
    """Live status of a machine.

    Attributes:
        machine_id: Unique machine ID.
        machine_name: Display name of the machine.
        state: Current sync state.
        files_pending: Number of files waiting in queue.
        uploads_in_progress: Number of files currently being uploaded.
        downloads_in_progress: Number of files currently being downloaded.
        upload_speed: Upload speed in bytes/second.
        download_speed: Download speed in bytes/second.
        file_count: Number of files synced by this machine.
        total_size: Total size of files synced by this machine.
        last_update: When this status was last updated.
    """

    machine_id: int
    machine_name: str
    state: SyncState = SyncState.OFFLINE
    files_pending: int = 0
    uploads_in_progress: int = 0
    downloads_in_progress: int = 0
    upload_speed: int = 0
    download_speed: int = 0
    file_count: int = 0
    total_size: int = 0
    last_update: datetime = field(default_factory=lambda: datetime.now(UTC))

    def to_dict(self) -> dict[str, str | int | None]:
        """Convert to JSON-serializable dict."""
        return {
            "machine_id": self.machine_id,
            "machine_name": self.machine_name,
            "state": self.state.value,
            "files_pending": self.files_pending,
            "uploads_in_progress": self.uploads_in_progress,
            "downloads_in_progress": self.downloads_in_progress,
            "upload_speed": self.upload_speed,
            "download_speed": self.download_speed,
            "file_count": self.file_count,
            "total_size": self.total_size,
            "last_update": self.last_update.isoformat(),
        }


class StatusHub:
    """Central hub for WebSocket connections and status broadcasting.

    Manages two types of connections:
    - Clients (sync daemons): Send status updates
    - Dashboards (browsers): Receive status updates

    Thread-safe for use with asyncio.
    """

    def __init__(
        self,
        offline_timeout_seconds: int = 30,
        db: Database | None = None,
    ) -> None:
        """Initialize the hub.

        Args:
            offline_timeout_seconds: Time without update before marking offline.
            db: Database instance for fetching file stats.
        """
        self._client_connections: dict[int, WebSocket] = {}  # machine_id -> ws
        self._dashboard_connections: set[WebSocket] = set()
        self._machine_status: dict[int, MachineStatus] = {}
        self._offline_timeout = offline_timeout_seconds
        self._db = db
        self._lock = asyncio.Lock()

    def set_db(self, db: Database) -> None:
        """Set the database reference (for late binding)."""
        self._db = db

    def _fetch_machine_stats(self, machine_id: int) -> tuple[int, int]:
        """Fetch file count and total size for a machine.

        Returns:
            Tuple of (file_count, total_size).
        """
        if not self._db:
            return (0, 0)
        try:
            stats = self._db.get_machine_stats(machine_id)
            return (stats.get("file_count", 0), stats.get("total_size", 0))
        except Exception:
            logger.warning("Failed to fetch stats for machine %d", machine_id)
            return (0, 0)

    async def connect_client(
        self,
        websocket: WebSocket,
        machine_id: int,
        machine_name: str,
    ) -> None:
        """Register a client connection.

        Args:
            websocket: The WebSocket connection.
            machine_id: ID of the machine.
            machine_name: Name of the machine.
        """
        await websocket.accept()

        # Fetch initial stats from database
        file_count, total_size = self._fetch_machine_stats(machine_id)

        async with self._lock:
            # Close old connection if exists
            old_ws = self._client_connections.get(machine_id)
            if old_ws and old_ws.client_state == WebSocketState.CONNECTED:
                with contextlib.suppress(Exception):
                    await old_ws.close()

            self._client_connections[machine_id] = websocket

            # Initialize status if not exists
            if machine_id not in self._machine_status:
                self._machine_status[machine_id] = MachineStatus(
                    machine_id=machine_id,
                    machine_name=machine_name,
                    state=SyncState.IDLE,
                    file_count=file_count,
                    total_size=total_size,
                )
            else:
                self._machine_status[machine_id].state = SyncState.IDLE
                self._machine_status[machine_id].file_count = file_count
                self._machine_status[machine_id].total_size = total_size
                self._machine_status[machine_id].last_update = datetime.now(UTC)

        logger.info("Client connected: %s (id=%d)", machine_name, machine_id)

        # Broadcast updated status
        await self._broadcast_status(machine_id)

    async def disconnect_client(self, machine_id: int) -> None:
        """Handle client disconnection.

        Args:
            machine_id: ID of the machine that disconnected.
        """
        async with self._lock:
            self._client_connections.pop(machine_id, None)

            if machine_id in self._machine_status:
                self._machine_status[machine_id].state = SyncState.OFFLINE
                self._machine_status[machine_id].last_update = datetime.now(UTC)

        logger.info("Client disconnected: machine_id=%d", machine_id)

        # Broadcast updated status
        await self._broadcast_status(machine_id)

    async def connect_dashboard(self, websocket: WebSocket) -> None:
        """Register a dashboard connection.

        Args:
            websocket: The WebSocket connection.
        """
        await websocket.accept()

        async with self._lock:
            self._dashboard_connections.add(websocket)

        logger.info("Dashboard connected")

        # Send current status of all machines
        await self._send_all_status(websocket)

    async def disconnect_dashboard(self, websocket: WebSocket) -> None:
        """Handle dashboard disconnection.

        Args:
            websocket: The WebSocket that disconnected.
        """
        async with self._lock:
            self._dashboard_connections.discard(websocket)

        logger.info("Dashboard disconnected")

    async def update_status(
        self,
        machine_id: int,
        state: SyncState | None = None,
        files_pending: int | None = None,
        uploads_in_progress: int | None = None,
        downloads_in_progress: int | None = None,
        upload_speed: int | None = None,
        download_speed: int | None = None,
    ) -> None:
        """Update machine status.

        Args:
            machine_id: ID of the machine.
            state: New sync state.
            files_pending: Number of files waiting in queue.
            uploads_in_progress: Number of files being uploaded.
            downloads_in_progress: Number of files being downloaded.
            upload_speed: Upload speed in bytes/second.
            download_speed: Download speed in bytes/second.
        """
        # Check if we should refresh file stats from database
        # Refresh when: state changes to IDLE, or a transfer just completed
        refresh_stats = False
        async with self._lock:
            if machine_id in self._machine_status:
                status = self._machine_status[machine_id]
                old_state = status.state

                # Refresh on state change to IDLE (sync completed)
                if state == SyncState.IDLE and old_state != SyncState.IDLE:
                    refresh_stats = True

                # Refresh when uploads decrease (upload just completed)
                if (
                    uploads_in_progress is not None
                    and uploads_in_progress < status.uploads_in_progress
                ):
                    refresh_stats = True

                # Refresh when downloads decrease (download just completed)
                if (
                    downloads_in_progress is not None
                    and downloads_in_progress < status.downloads_in_progress
                ):
                    refresh_stats = True

        # Fetch stats outside the lock if needed
        file_count, total_size = 0, 0
        if refresh_stats:
            file_count, total_size = self._fetch_machine_stats(machine_id)

        async with self._lock:
            if machine_id not in self._machine_status:
                logger.warning("Status update for unknown machine: %d", machine_id)
                return

            status = self._machine_status[machine_id]
            if state is not None:
                status.state = state
            if files_pending is not None:
                status.files_pending = files_pending
            if uploads_in_progress is not None:
                status.uploads_in_progress = uploads_in_progress
            if downloads_in_progress is not None:
                status.downloads_in_progress = downloads_in_progress
            if upload_speed is not None:
                status.upload_speed = upload_speed
            if download_speed is not None:
                status.download_speed = download_speed

            # Update stats if we refreshed them
            if refresh_stats:
                status.file_count = file_count
                status.total_size = total_size

            status.last_update = datetime.now(UTC)

        # Broadcast updated status
        await self._broadcast_status(machine_id)

    async def handle_client_message(self, machine_id: int, data: dict[str, Any]) -> None:
        """Handle incoming message from client.

        Expected message formats:
            {
                "type": "status",
                "state": "syncing",
                "files_pending": 5,
                "uploads_in_progress": 2,
                "downloads_in_progress": 1,
                "upload_speed": 1500000,
                "download_speed": 2000000
            }
            {"type": "heartbeat"}

        Args:
            machine_id: ID of the machine.
            data: Message data.
        """
        msg_type = data.get("type")

        if msg_type == "status":
            # Status update
            state_str = data.get("state")
            state = SyncState(state_str) if state_str else None
            await self.update_status(
                machine_id=machine_id,
                state=state,
                files_pending=data.get("files_pending"),
                uploads_in_progress=data.get("uploads_in_progress"),
                downloads_in_progress=data.get("downloads_in_progress"),
                upload_speed=data.get("upload_speed"),
                download_speed=data.get("download_speed"),
            )
        elif msg_type == "heartbeat":
            # Just update last_update timestamp
            async with self._lock:
                if machine_id in self._machine_status:
                    self._machine_status[machine_id].last_update = datetime.now(UTC)
        else:
            logger.warning("Unknown message type from client %d: %s", machine_id, msg_type)

    async def get_status(self, machine_id: int) -> MachineStatus | None:
        """Get status of a machine.

        Args:
            machine_id: ID of the machine.

        Returns:
            MachineStatus or None if not found.
        """
        async with self._lock:
            return self._machine_status.get(machine_id)

    async def get_all_status(self) -> list[MachineStatus]:
        """Get status of all machines.

        Returns:
            List of MachineStatus objects.
        """
        async with self._lock:
            return list(self._machine_status.values())

    async def _broadcast_status(self, machine_id: int) -> None:
        """Broadcast status of a machine to all dashboards.

        Args:
            machine_id: ID of the machine.
        """
        async with self._lock:
            status = self._machine_status.get(machine_id)
            if not status:
                return

            message = json.dumps({
                "type": "status_update",
                "machine": status.to_dict(),
            })

            # Send to all connected dashboards
            disconnected = []
            for ws in self._dashboard_connections:
                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(message)
                except Exception:
                    disconnected.append(ws)

            # Clean up disconnected
            for ws in disconnected:
                self._dashboard_connections.discard(ws)

    async def _send_all_status(self, websocket: WebSocket) -> None:
        """Send status of all machines to a dashboard.

        Args:
            websocket: The dashboard WebSocket.
        """
        async with self._lock:
            machines = [s.to_dict() for s in self._machine_status.values()]

        message = json.dumps({
            "type": "all_status",
            "machines": machines,
        })

        with contextlib.suppress(Exception):
            await websocket.send_text(message)

    async def notify_file_change(
        self,
        action: str,
        file_path: str,
        timestamp: str,
        exclude_machine_id: int | None = None,
    ) -> None:
        """Notify all connected clients about a file change.

        This is used to push server-side changes (admin delete, restore, etc.)
        to connected clients so they can sync immediately.

        Args:
            action: Change action (CREATED, UPDATED, DELETED).
            file_path: Path of the changed file.
            timestamp: ISO timestamp of the change.
            exclude_machine_id: Optional machine ID to exclude from notification
                               (e.g., the machine that made the change).
        """
        message = json.dumps({
            "type": "file_change",
            "action": action,
            "path": file_path,
            "timestamp": timestamp,
        })

        async with self._lock:
            disconnected = []
            for machine_id, ws in self._client_connections.items():
                # Skip the machine that made the change
                if exclude_machine_id and machine_id == exclude_machine_id:
                    continue

                try:
                    if ws.client_state == WebSocketState.CONNECTED:
                        await ws.send_text(message)
                        logger.debug(
                            "Sent file_change to machine %d: %s %s",
                            machine_id, action, file_path,
                        )
                except Exception:
                    disconnected.append(machine_id)

            # Clean up disconnected clients
            for machine_id in disconnected:
                self._client_connections.pop(machine_id, None)
                if machine_id in self._machine_status:
                    self._machine_status[machine_id].state = SyncState.OFFLINE

    def notify_file_change_sync(
        self,
        action: str,
        file_path: str,
        timestamp: str,
        exclude_machine_id: int | None = None,
    ) -> None:
        """Synchronous wrapper for notify_file_change.

        For use from non-async database code.

        Args:
            action: Change action (CREATED, UPDATED, DELETED).
            file_path: Path of the changed file.
            timestamp: ISO timestamp of the change.
            exclude_machine_id: Optional machine ID to exclude.
        """
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            # No event loop running - can't notify
            logger.debug("No event loop, skipping file change notification")
            return

        asyncio.create_task(
            self.notify_file_change(action, file_path, timestamp, exclude_machine_id)
        )


# Global hub instance (created by app)
_hub: StatusHub | None = None


def get_hub() -> StatusHub:
    """Get the global StatusHub instance."""
    global _hub
    if _hub is None:
        _hub = StatusHub()
    return _hub


def set_hub(hub: StatusHub) -> None:
    """Set the global StatusHub instance."""
    global _hub
    _hub = hub


# WebSocket router
router = APIRouter(tags=["websocket"])


@router.websocket("/ws/client/{token}")
async def websocket_client(websocket: WebSocket, token: str) -> None:
    """WebSocket endpoint for sync clients.

    Clients connect with their auth token to send status updates.

    Message format (client -> server):
        {"type": "status", "state": "syncing", "files_pending": 5, "bytes_per_sec": 1500000}
        {"type": "heartbeat"}

    Args:
        websocket: The WebSocket connection.
        token: Authentication token.
    """
    # Get database from app state
    db: Database = websocket.app.state.db
    hub = get_hub()

    # Set database on hub for stats fetching
    hub.set_db(db)

    # Validate token
    auth_token = db.validate_token(token)
    if not auth_token:
        await websocket.close(code=4001, reason="Invalid token")
        return

    machine = db.get_machine(auth_token.machine_id)
    if not machine:
        await websocket.close(code=4001, reason="Machine not found")
        return

    # Connect
    await hub.connect_client(websocket, machine.id, machine.name)

    try:
        while True:
            data = await websocket.receive_json()
            await hub.handle_client_message(machine.id, data)
    except WebSocketDisconnect:
        await hub.disconnect_client(machine.id)
    except Exception as e:
        logger.exception("Error in client WebSocket: %s", e)
        await hub.disconnect_client(machine.id)


@router.websocket("/ws/dashboard")
async def websocket_dashboard(websocket: WebSocket) -> None:
    """WebSocket endpoint for dashboard.

    Dashboard connects to receive status updates from all machines.
    No authentication required (assumes dashboard is behind admin auth).

    Message format (server -> dashboard):
        {"type": "all_status", "machines": [...]}
        {"type": "status_update", "machine": {...}}

    Args:
        websocket: The WebSocket connection.
    """
    hub = get_hub()

    await hub.connect_dashboard(websocket)

    try:
        while True:
            # Dashboard doesn't send messages, just wait for disconnect
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect_dashboard(websocket)
    except Exception as e:
        logger.exception("Error in dashboard WebSocket: %s", e)
        await hub.disconnect_dashboard(websocket)
