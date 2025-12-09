"""System tray icon for SyncAgent.

This module provides:
- System tray icon with status indicators
- Context menu for common actions
- Status notifications
- Background sync monitoring

Requires pystray and Pillow for cross-platform tray icon support.
"""

from __future__ import annotations

import platform
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path

from PIL import Image, ImageDraw

# pystray import with fallback
PYSTRAY_AVAILABLE: bool
try:
    import pystray
    from pystray import Icon, Menu, MenuItem

    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    pystray = None  # type: ignore[assignment]
    Icon = None  # noqa: N806  # type: ignore[misc]
    Menu = None  # noqa: N806  # type: ignore[misc]
    MenuItem = None  # noqa: N806  # type: ignore[misc]



class TrayStatus(Enum):
    """Status states for the tray icon."""

    IDLE = auto()  # No sync in progress
    SYNCING = auto()  # Sync in progress
    ERROR = auto()  # Sync error occurred
    CONFLICT = auto()  # Conflict detected
    OFFLINE = auto()  # No connection to server
    PAUSED = auto()  # Sync paused


# Color scheme for status icons
STATUS_COLORS = {
    TrayStatus.IDLE: "#4CAF50",  # Green
    TrayStatus.SYNCING: "#2196F3",  # Blue
    TrayStatus.ERROR: "#F44336",  # Red
    TrayStatus.CONFLICT: "#FF9800",  # Orange
    TrayStatus.OFFLINE: "#9E9E9E",  # Gray
    TrayStatus.PAUSED: "#607D8B",  # Blue Gray
}


@dataclass
class TrayCallbacks:
    """Callbacks for tray menu actions.

    Attributes:
        on_sync_now: Called when "Sync Now" is clicked
        on_open_folder: Called when "Open Sync Folder" is clicked
        on_open_dashboard: Called when "Open Dashboard" is clicked
        on_pause_resume: Called when "Pause/Resume" is clicked
        on_settings: Called when "Settings" is clicked
        on_quit: Called when "Quit" is clicked
    """

    on_sync_now: Callable[[], None] | None = None
    on_open_folder: Callable[[], None] | None = None
    on_open_dashboard: Callable[[], None] | None = None
    on_pause_resume: Callable[[], None] | None = None
    on_settings: Callable[[], None] | None = None
    on_quit: Callable[[], None] | None = None


def create_icon_image(status: TrayStatus, size: int = 64) -> Image.Image:
    """Create a status icon image.

    Args:
        status: The status to represent
        size: Icon size in pixels

    Returns:
        PIL Image with the status icon
    """
    # Create a new image with transparency
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)

    # Get color for status
    color = STATUS_COLORS.get(status, STATUS_COLORS[TrayStatus.IDLE])

    # Draw the icon based on status
    margin = size // 8
    center = size // 2

    if status == TrayStatus.SYNCING:
        # Draw rotating arrows (simplified as circular arrows)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            outline=color,
            width=size // 10,
        )
        # Add arrow heads
        arrow_size = size // 6
        draw.polygon(
            [
                (size - margin - arrow_size, margin),
                (size - margin, margin + arrow_size),
                (size - margin - arrow_size * 2, margin + arrow_size),
            ],
            fill=color,
        )

    elif status == TrayStatus.ERROR:
        # Draw exclamation mark in circle
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color,
        )
        # Exclamation mark
        bar_width = size // 8
        draw.rectangle(
            [
                center - bar_width // 2,
                margin + size // 6,
                center + bar_width // 2,
                size - margin - size // 3,
            ],
            fill="white",
        )
        draw.ellipse(
            [
                center - bar_width // 2,
                size - margin - size // 5,
                center + bar_width // 2,
                size - margin - size // 10,
            ],
            fill="white",
        )

    elif status == TrayStatus.CONFLICT:
        # Draw warning triangle
        points = [
            (center, margin),
            (size - margin, size - margin),
            (margin, size - margin),
        ]
        draw.polygon(points, fill=color)
        # Exclamation mark
        bar_width = size // 10
        draw.rectangle(
            [
                center - bar_width // 2,
                margin + size // 4,
                center + bar_width // 2,
                size - margin - size // 4,
            ],
            fill="white",
        )
        draw.ellipse(
            [
                center - bar_width // 2,
                size - margin - size // 6,
                center + bar_width // 2,
                size - margin - size // 12,
            ],
            fill="white",
        )

    elif status == TrayStatus.OFFLINE:
        # Draw cloud with X
        draw.ellipse(
            [margin, margin + size // 4, size - margin, size - margin],
            fill=color,
        )
        # X mark
        line_width = size // 12
        offset = size // 4
        draw.line(
            [(margin + offset, margin + offset + size // 4),
             (size - margin - offset, size - margin - offset)],
            fill="white",
            width=line_width,
        )
        draw.line(
            [(size - margin - offset, margin + offset + size // 4),
             (margin + offset, size - margin - offset)],
            fill="white",
            width=line_width,
        )

    elif status == TrayStatus.PAUSED:
        # Draw pause symbol (two bars)
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color,
        )
        bar_width = size // 8
        bar_height = size // 3
        gap = size // 8
        draw.rectangle(
            [
                center - gap - bar_width,
                center - bar_height // 2,
                center - gap,
                center + bar_height // 2,
            ],
            fill="white",
        )
        draw.rectangle(
            [
                center + gap,
                center - bar_height // 2,
                center + gap + bar_width,
                center + bar_height // 2,
            ],
            fill="white",
        )

    else:  # IDLE - default
        # Draw checkmark in circle
        draw.ellipse(
            [margin, margin, size - margin, size - margin],
            fill=color,
        )
        # Checkmark
        line_width = size // 10
        check_points = [
            (margin + size // 4, center),
            (center - size // 10, size - margin - size // 4),
            (size - margin - size // 6, margin + size // 4),
        ]
        draw.line(check_points[:2], fill="white", width=line_width)
        draw.line(check_points[1:], fill="white", width=line_width)

    return image


def open_folder(folder_path: Path) -> None:
    """Open a folder in the system file manager.

    Args:
        folder_path: Path to the folder to open
    """
    system = platform.system()

    if system == "Windows":
        subprocess.run(["explorer", str(folder_path)], check=False)
    elif system == "Darwin":
        subprocess.run(["open", str(folder_path)], check=False)
    else:  # Linux
        subprocess.run(["xdg-open", str(folder_path)], check=False)


def open_url(url: str) -> None:
    """Open a URL in the default browser.

    Args:
        url: URL to open
    """
    import webbrowser

    webbrowser.open(url)


class SyncAgentTray:
    """System tray icon for SyncAgent.

    Provides a system tray icon with status indicators and context menu.
    """

    def __init__(
        self,
        sync_folder: Path,
        dashboard_url: str = "http://localhost:8000",
        callbacks: TrayCallbacks | None = None,
    ) -> None:
        """Initialize the tray icon.

        Args:
            sync_folder: Path to the sync folder
            dashboard_url: URL to the web dashboard
            callbacks: Optional callbacks for menu actions

        Raises:
            ImportError: If pystray is not available
        """
        if not PYSTRAY_AVAILABLE:
            raise ImportError(
                "pystray is required for tray icon. "
                "Install with: pip install pystray pillow"
            )

        self._sync_folder = sync_folder
        self._dashboard_url = dashboard_url
        self._callbacks = callbacks or TrayCallbacks()
        self._status = TrayStatus.IDLE
        self._paused = False
        self._icon: pystray.Icon | None = None
        self._thread: threading.Thread | None = None
        self._status_text = "SyncAgent - Idle"

    @property
    def status(self) -> TrayStatus:
        """Get current status."""
        return self._status

    @status.setter
    def status(self, value: TrayStatus) -> None:
        """Set status and update icon."""
        self._status = value
        self._update_icon()

    @property
    def paused(self) -> bool:
        """Check if sync is paused."""
        return self._paused

    @paused.setter
    def paused(self, value: bool) -> None:
        """Set paused state."""
        self._paused = value
        if value:
            self._status = TrayStatus.PAUSED
        self._update_icon()

    def _get_status_text(self) -> str:
        """Get status text for tooltip."""
        status_texts = {
            TrayStatus.IDLE: "SyncAgent - Up to date",
            TrayStatus.SYNCING: "SyncAgent - Syncing...",
            TrayStatus.ERROR: "SyncAgent - Error",
            TrayStatus.CONFLICT: "SyncAgent - Conflict detected",
            TrayStatus.OFFLINE: "SyncAgent - Offline",
            TrayStatus.PAUSED: "SyncAgent - Paused",
        }
        return status_texts.get(self._status, "SyncAgent")

    def _update_icon(self) -> None:
        """Update the tray icon based on current status."""
        if self._icon is None:
            return

        self._icon.icon = create_icon_image(self._status)
        self._icon.title = self._get_status_text()

    def _on_sync_now(self) -> None:
        """Handle Sync Now menu item."""
        if self._callbacks.on_sync_now:
            self._callbacks.on_sync_now()

    def _on_open_folder(self) -> None:
        """Handle Open Sync Folder menu item."""
        if self._callbacks.on_open_folder:
            self._callbacks.on_open_folder()
        else:
            open_folder(self._sync_folder)

    def _on_open_dashboard(self) -> None:
        """Handle Open Dashboard menu item."""
        if self._callbacks.on_open_dashboard:
            self._callbacks.on_open_dashboard()
        else:
            open_url(self._dashboard_url)

    def _on_pause_resume(self) -> None:
        """Handle Pause/Resume menu item."""
        self._paused = not self._paused
        if self._callbacks.on_pause_resume:
            self._callbacks.on_pause_resume()
        self._update_icon()

    def _on_settings(self) -> None:
        """Handle Settings menu item."""
        if self._callbacks.on_settings:
            self._callbacks.on_settings()

    def _on_quit(self) -> None:
        """Handle Quit menu item."""
        if self._callbacks.on_quit:
            self._callbacks.on_quit()
        self.stop()

    def _get_pause_text(self) -> str:
        """Get text for pause/resume menu item."""
        return "Resume Sync" if self._paused else "Pause Sync"

    def _create_menu(self) -> pystray.Menu:
        """Create the context menu."""
        return Menu(
            MenuItem("Sync Now", self._on_sync_now),
            MenuItem("Open Sync Folder", self._on_open_folder),
            MenuItem("Open Dashboard", self._on_open_dashboard),
            Menu.SEPARATOR,
            MenuItem(
                lambda _: self._get_pause_text(),
                self._on_pause_resume,
            ),
            Menu.SEPARATOR,
            MenuItem("Quit SyncAgent", self._on_quit),
        )

    def start(self, blocking: bool = True) -> None:
        """Start the tray icon.

        Args:
            blocking: If True, blocks until stop() is called.
                     If False, runs in a background thread.
        """
        if self._icon is not None:
            return  # Already running

        self._icon = Icon(
            name="SyncAgent",
            icon=create_icon_image(self._status),
            title=self._get_status_text(),
            menu=self._create_menu(),
        )

        if blocking:
            self._icon.run()
        else:
            self._thread = threading.Thread(target=self._icon.run, daemon=True)
            self._thread.start()

    def stop(self) -> None:
        """Stop the tray icon."""
        if self._icon is not None:
            self._icon.stop()
            self._icon = None

    def notify(self, title: str, message: str) -> None:
        """Show a notification.

        Args:
            title: Notification title
            message: Notification message
        """
        if self._icon is not None:
            self._icon.notify(message, title)

    def set_syncing(self, file_count: int = 0) -> None:
        """Set status to syncing.

        Args:
            file_count: Number of files being synced
        """
        self._status = TrayStatus.SYNCING
        if file_count > 0:
            self._status_text = f"SyncAgent - Syncing {file_count} files..."
        else:
            self._status_text = "SyncAgent - Syncing..."
        self._update_icon()

    def set_idle(self) -> None:
        """Set status to idle (up to date)."""
        self._status = TrayStatus.IDLE
        self._status_text = "SyncAgent - Up to date"
        self._update_icon()

    def set_error(self, message: str = "") -> None:
        """Set status to error.

        Args:
            message: Error message
        """
        self._status = TrayStatus.ERROR
        self._status_text = f"SyncAgent - Error: {message}" if message else "SyncAgent - Error"
        self._update_icon()

    def set_conflict(self, count: int = 1) -> None:
        """Set status to conflict.

        Args:
            count: Number of conflicts
        """
        self._status = TrayStatus.CONFLICT
        self._status_text = f"SyncAgent - {count} conflict(s)"
        self._update_icon()

    def set_offline(self) -> None:
        """Set status to offline."""
        self._status = TrayStatus.OFFLINE
        self._status_text = "SyncAgent - Offline"
        self._update_icon()


def run_tray(
    sync_folder: Path,
    dashboard_url: str = "http://localhost:8000",
    callbacks: TrayCallbacks | None = None,
) -> SyncAgentTray:
    """Create and start the tray icon in a background thread.

    Args:
        sync_folder: Path to the sync folder
        dashboard_url: URL to the web dashboard
        callbacks: Optional callbacks for menu actions

    Returns:
        The SyncAgentTray instance
    """
    tray = SyncAgentTray(sync_folder, dashboard_url, callbacks)
    tray.start(blocking=False)
    return tray
