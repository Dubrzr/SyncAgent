"""Cross-platform system notifications for SyncAgent.

This module provides:
- Native OS notifications (Windows toast, macOS notification center, Linux notify-send)
- Fallback to console output if notifications unavailable
"""

from __future__ import annotations

import logging
import platform
import subprocess
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)


class NotificationType(Enum):
    """Type of notification."""

    INFO = auto()
    WARNING = auto()
    ERROR = auto()
    CONFLICT = auto()


@dataclass
class Notification:
    """Represents a notification to display."""

    title: str
    message: str
    type: NotificationType = NotificationType.INFO


def _notify_windows(notification: Notification) -> bool:
    """Send notification on Windows using PowerShell toast.

    Args:
        notification: The notification to send.

    Returns:
        True if notification was sent successfully.
    """
    try:
        # Use PowerShell to create a toast notification
        ps_script = f'''
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

        $template = @"
        <toast>
            <visual>
                <binding template="ToastText02">
                    <text id="1">{notification.title}</text>
                    <text id="2">{notification.message}</text>
                </binding>
            </visual>
        </toast>
"@

        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($template)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier("SyncAgent").Show($toast)
        '''

        subprocess.run(
            ["powershell", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
            capture_output=True,
            check=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        return True
    except Exception as e:
        logger.debug(f"Windows notification failed: {e}")
        return False


def _notify_windows_fallback(notification: Notification) -> bool:
    """Fallback Windows notification using plyer if available.

    Args:
        notification: The notification to send.

    Returns:
        True if notification was sent successfully.
    """
    try:
        # Try using plyer if available (cross-platform library)
        from plyer import notification as plyer_notif  # type: ignore[import-not-found]

        plyer_notif.notify(
            title=notification.title,
            message=notification.message,
            app_name="SyncAgent",
            timeout=10,
        )
        return True
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"plyer notification failed: {e}")

    # Console fallback
    return False


def _notify_macos(notification: Notification) -> bool:
    """Send notification on macOS using osascript.

    Args:
        notification: The notification to send.

    Returns:
        True if notification was sent successfully.
    """
    try:
        # Escape quotes in title and message
        title = notification.title.replace('"', '\\"')
        message = notification.message.replace('"', '\\"')

        script = f'display notification "{message}" with title "{title}"'
        subprocess.run(
            ["osascript", "-e", script],
            capture_output=True,
            check=True,
        )
        return True
    except Exception as e:
        logger.debug(f"macOS notification failed: {e}")
        return False


def _notify_linux(notification: Notification) -> bool:
    """Send notification on Linux using notify-send.

    Args:
        notification: The notification to send.

    Returns:
        True if notification was sent successfully.
    """
    try:
        # Map notification type to urgency
        urgency_map = {
            NotificationType.INFO: "normal",
            NotificationType.WARNING: "normal",
            NotificationType.ERROR: "critical",
            NotificationType.CONFLICT: "critical",
        }
        urgency = urgency_map.get(notification.type, "normal")

        subprocess.run(
            [
                "notify-send",
                "--urgency", urgency,
                "--app-name", "SyncAgent",
                notification.title,
                notification.message,
            ],
            capture_output=True,
            check=True,
        )
        return True
    except FileNotFoundError:
        logger.debug("notify-send not found")
        return False
    except Exception as e:
        logger.debug(f"Linux notification failed: {e}")
        return False


def send_notification(notification: Notification) -> bool:
    """Send a system notification.

    Uses native OS notification system:
    - Windows: Toast notification via PowerShell
    - macOS: Notification Center via osascript
    - Linux: notify-send

    Args:
        notification: The notification to send.

    Returns:
        True if notification was sent, False if failed or unavailable.
    """
    system = platform.system()

    if system == "Windows":
        if _notify_windows(notification):
            return True
        return _notify_windows_fallback(notification)
    elif system == "Darwin":
        return _notify_macos(notification)
    elif system == "Linux":
        return _notify_linux(notification)
    else:
        logger.warning(f"Notifications not supported on {system}")
        return False


def notify_conflict(filename: str, machine_name: str) -> bool:
    """Send a conflict notification.

    Args:
        filename: Name of the conflicting file.
        machine_name: Name of the machine that caused the conflict.

    Returns:
        True if notification was sent.
    """
    return send_notification(Notification(
        title="SyncAgent - Conflict Detected",
        message=f"'{filename}' has a conflict. Check the .conflict-* file.",
        type=NotificationType.CONFLICT,
    ))


def notify_sync_complete(uploaded: int, downloaded: int) -> bool:
    """Send a sync complete notification.

    Args:
        uploaded: Number of files uploaded.
        downloaded: Number of files downloaded.

    Returns:
        True if notification was sent.
    """
    if uploaded == 0 and downloaded == 0:
        return False  # Don't notify if nothing happened

    parts = []
    if uploaded > 0:
        parts.append(f"{uploaded} uploaded")
    if downloaded > 0:
        parts.append(f"{downloaded} downloaded")

    return send_notification(Notification(
        title="SyncAgent - Sync Complete",
        message=", ".join(parts),
        type=NotificationType.INFO,
    ))


def notify_error(message: str) -> bool:
    """Send an error notification.

    Args:
        message: Error message.

    Returns:
        True if notification was sent.
    """
    return send_notification(Notification(
        title="SyncAgent - Error",
        message=message,
        type=NotificationType.ERROR,
    ))
