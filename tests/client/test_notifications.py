"""Tests for notification system."""

from unittest.mock import MagicMock, patch

from syncagent.client.notifications import (
    Notification,
    NotificationType,
    notify_conflict,
    notify_error,
    notify_sync_complete,
    send_notification,
)


class TestNotification:
    """Tests for Notification dataclass."""

    def test_notification_creation(self) -> None:
        """Should create notification with all fields."""
        notif = Notification(
            title="Test Title",
            message="Test message",
            type=NotificationType.INFO,
        )
        assert notif.title == "Test Title"
        assert notif.message == "Test message"
        assert notif.type == NotificationType.INFO

    def test_notification_default_type(self) -> None:
        """Should default to INFO type."""
        notif = Notification(title="Title", message="Message")
        assert notif.type == NotificationType.INFO


class TestNotificationHelpers:
    """Tests for notification helper functions."""

    @patch("syncagent.client.notifications.send_notification")
    def test_notify_conflict(self, mock_send: MagicMock) -> None:
        """Should send conflict notification."""
        mock_send.return_value = True

        result = notify_conflict("document.txt", "MyPC")

        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Conflict" in call_args.title
        assert "document.txt" in call_args.message
        assert call_args.type == NotificationType.CONFLICT

    @patch("syncagent.client.notifications.send_notification")
    def test_notify_sync_complete_with_changes(self, mock_send: MagicMock) -> None:
        """Should send sync complete notification when changes occurred."""
        mock_send.return_value = True

        result = notify_sync_complete(uploaded=3, downloaded=2)

        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Sync Complete" in call_args.title
        assert "3 uploaded" in call_args.message
        assert "2 downloaded" in call_args.message

    @patch("syncagent.client.notifications.send_notification")
    def test_notify_sync_complete_no_changes(self, mock_send: MagicMock) -> None:
        """Should not send notification when no changes."""
        result = notify_sync_complete(uploaded=0, downloaded=0)

        assert result is False
        mock_send.assert_not_called()

    @patch("syncagent.client.notifications.send_notification")
    def test_notify_error(self, mock_send: MagicMock) -> None:
        """Should send error notification."""
        mock_send.return_value = True

        result = notify_error("Connection failed")

        assert result is True
        mock_send.assert_called_once()
        call_args = mock_send.call_args[0][0]
        assert "Error" in call_args.title
        assert "Connection failed" in call_args.message
        assert call_args.type == NotificationType.ERROR


class TestSendNotification:
    """Tests for send_notification function."""

    @patch("syncagent.client.notifications._notify_windows")
    @patch("syncagent.client.notifications.platform.system")
    def test_windows_notification(
        self, mock_system: MagicMock, mock_notify: MagicMock
    ) -> None:
        """Should use Windows notification on Windows."""
        mock_system.return_value = "Windows"
        mock_notify.return_value = True

        notif = Notification(title="Test", message="Message")
        result = send_notification(notif)

        assert result is True
        mock_notify.assert_called_once_with(notif)

    @patch("syncagent.client.notifications._notify_macos")
    @patch("syncagent.client.notifications.platform.system")
    def test_macos_notification(
        self, mock_system: MagicMock, mock_notify: MagicMock
    ) -> None:
        """Should use macOS notification on Darwin."""
        mock_system.return_value = "Darwin"
        mock_notify.return_value = True

        notif = Notification(title="Test", message="Message")
        result = send_notification(notif)

        assert result is True
        mock_notify.assert_called_once_with(notif)

    @patch("syncagent.client.notifications._notify_linux")
    @patch("syncagent.client.notifications.platform.system")
    def test_linux_notification(
        self, mock_system: MagicMock, mock_notify: MagicMock
    ) -> None:
        """Should use Linux notification on Linux."""
        mock_system.return_value = "Linux"
        mock_notify.return_value = True

        notif = Notification(title="Test", message="Message")
        result = send_notification(notif)

        assert result is True
        mock_notify.assert_called_once_with(notif)

    @patch("syncagent.client.notifications.platform.system")
    def test_unsupported_platform(self, mock_system: MagicMock) -> None:
        """Should return False on unsupported platform."""
        mock_system.return_value = "FreeBSD"

        notif = Notification(title="Test", message="Message")
        result = send_notification(notif)

        assert result is False

    @patch("syncagent.client.notifications._notify_windows")
    @patch("syncagent.client.notifications._notify_windows_fallback")
    @patch("syncagent.client.notifications.platform.system")
    def test_windows_fallback(
        self,
        mock_system: MagicMock,
        mock_fallback: MagicMock,
        mock_notify: MagicMock,
    ) -> None:
        """Should try fallback if Windows notification fails."""
        mock_system.return_value = "Windows"
        mock_notify.return_value = False
        mock_fallback.return_value = True

        notif = Notification(title="Test", message="Message")
        result = send_notification(notif)

        assert result is True
        mock_notify.assert_called_once()
        mock_fallback.assert_called_once()
