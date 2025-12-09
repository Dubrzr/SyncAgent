"""Tests for system tray icon module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from syncagent.client.tray import (
    PYSTRAY_AVAILABLE,
    STATUS_COLORS,
    SyncAgentTray,
    TrayCallbacks,
    TrayStatus,
    create_icon_image,
    open_folder,
    open_url,
    run_tray,
)


class TestTrayStatus:
    """Tests for TrayStatus enum."""

    def test_all_statuses_defined(self) -> None:
        """Should have all expected status values."""
        assert TrayStatus.IDLE is not None
        assert TrayStatus.SYNCING is not None
        assert TrayStatus.ERROR is not None
        assert TrayStatus.CONFLICT is not None
        assert TrayStatus.OFFLINE is not None
        assert TrayStatus.PAUSED is not None

    def test_status_colors_complete(self) -> None:
        """Should have a color for each status."""
        for status in TrayStatus:
            assert status in STATUS_COLORS
            assert STATUS_COLORS[status].startswith("#")


class TestTrayCallbacks:
    """Tests for TrayCallbacks dataclass."""

    def test_default_callbacks_none(self) -> None:
        """Should have None as default for all callbacks."""
        callbacks = TrayCallbacks()
        assert callbacks.on_sync_now is None
        assert callbacks.on_open_folder is None
        assert callbacks.on_open_dashboard is None
        assert callbacks.on_pause_resume is None
        assert callbacks.on_settings is None
        assert callbacks.on_quit is None

    def test_callbacks_can_be_set(self) -> None:
        """Should accept callback functions."""
        mock_fn = MagicMock()
        callbacks = TrayCallbacks(
            on_sync_now=mock_fn,
            on_quit=mock_fn,
        )
        assert callbacks.on_sync_now is mock_fn
        assert callbacks.on_quit is mock_fn


class TestCreateIconImage:
    """Tests for icon creation."""

    def test_creates_image(self) -> None:
        """Should create a PIL Image."""
        image = create_icon_image(TrayStatus.IDLE)
        assert isinstance(image, Image.Image)

    def test_default_size(self) -> None:
        """Should create 64x64 image by default."""
        image = create_icon_image(TrayStatus.IDLE)
        assert image.size == (64, 64)

    def test_custom_size(self) -> None:
        """Should respect custom size."""
        image = create_icon_image(TrayStatus.IDLE, size=128)
        assert image.size == (128, 128)

    def test_rgba_mode(self) -> None:
        """Should create RGBA image for transparency."""
        image = create_icon_image(TrayStatus.IDLE)
        assert image.mode == "RGBA"

    @pytest.mark.parametrize("status", list(TrayStatus))
    def test_creates_image_for_all_statuses(self, status: TrayStatus) -> None:
        """Should create image for all status types."""
        image = create_icon_image(status)
        assert isinstance(image, Image.Image)
        assert image.size == (64, 64)


class TestOpenFolder:
    """Tests for folder opening."""

    @patch("syncagent.client.tray.platform.system", return_value="Windows")
    @patch("syncagent.client.tray.subprocess.run")
    def test_open_folder_windows(
        self, mock_run: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use explorer on Windows."""
        open_folder(tmp_path)
        mock_run.assert_called_once_with(["explorer", str(tmp_path)], check=False)

    @patch("syncagent.client.tray.platform.system", return_value="Darwin")
    @patch("syncagent.client.tray.subprocess.run")
    def test_open_folder_macos(
        self, mock_run: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use open on macOS."""
        open_folder(tmp_path)
        mock_run.assert_called_once_with(["open", str(tmp_path)], check=False)

    @patch("syncagent.client.tray.platform.system", return_value="Linux")
    @patch("syncagent.client.tray.subprocess.run")
    def test_open_folder_linux(
        self, mock_run: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use xdg-open on Linux."""
        open_folder(tmp_path)
        mock_run.assert_called_once_with(["xdg-open", str(tmp_path)], check=False)


class TestOpenUrl:
    """Tests for URL opening."""

    @patch("webbrowser.open")
    def test_opens_url_in_browser(self, mock_open: MagicMock) -> None:
        """Should open URL in default browser."""
        open_url("http://localhost:8000")
        mock_open.assert_called_once_with("http://localhost:8000")


@pytest.mark.skipif(not PYSTRAY_AVAILABLE, reason="pystray not installed")
class TestSyncAgentTray:
    """Tests for SyncAgentTray class."""

    def test_init(self, tmp_path: Path) -> None:
        """Should initialize with required parameters."""
        tray = SyncAgentTray(tmp_path)
        assert tray._sync_folder == tmp_path
        assert tray._dashboard_url == "http://localhost:8000"
        assert tray._status == TrayStatus.IDLE
        assert tray._paused is False

    def test_init_with_custom_url(self, tmp_path: Path) -> None:
        """Should accept custom dashboard URL."""
        tray = SyncAgentTray(tmp_path, dashboard_url="http://example.com")
        assert tray._dashboard_url == "http://example.com"

    def test_init_with_callbacks(self, tmp_path: Path) -> None:
        """Should accept callbacks."""
        callbacks = TrayCallbacks(on_quit=MagicMock())
        tray = SyncAgentTray(tmp_path, callbacks=callbacks)
        assert tray._callbacks.on_quit is not None

    def test_status_property(self, tmp_path: Path) -> None:
        """Should get and set status."""
        tray = SyncAgentTray(tmp_path)
        assert tray.status == TrayStatus.IDLE
        tray._status = TrayStatus.SYNCING
        assert tray.status == TrayStatus.SYNCING  # type: ignore[comparison-overlap]

    def test_paused_property(self, tmp_path: Path) -> None:
        """Should get and set paused state."""
        tray = SyncAgentTray(tmp_path)
        assert tray.paused is False
        tray._paused = True
        assert tray.paused is True

    def test_get_status_text(self, tmp_path: Path) -> None:
        """Should return appropriate status text."""
        tray = SyncAgentTray(tmp_path)

        tray._status = TrayStatus.IDLE
        assert "Up to date" in tray._get_status_text()

        tray._status = TrayStatus.SYNCING
        assert "Syncing" in tray._get_status_text()

        tray._status = TrayStatus.ERROR
        assert "Error" in tray._get_status_text()

    def test_set_syncing(self, tmp_path: Path) -> None:
        """Should set syncing status."""
        tray = SyncAgentTray(tmp_path)
        tray.set_syncing()
        assert tray._status == TrayStatus.SYNCING

    def test_set_syncing_with_count(self, tmp_path: Path) -> None:
        """Should set syncing status with file count."""
        tray = SyncAgentTray(tmp_path)
        tray.set_syncing(5)
        assert tray._status == TrayStatus.SYNCING
        assert "5" in tray._status_text

    def test_set_idle(self, tmp_path: Path) -> None:
        """Should set idle status."""
        tray = SyncAgentTray(tmp_path)
        tray._status = TrayStatus.SYNCING
        tray.set_idle()
        assert tray._status == TrayStatus.IDLE

    def test_set_error(self, tmp_path: Path) -> None:
        """Should set error status."""
        tray = SyncAgentTray(tmp_path)
        tray.set_error("Connection failed")
        assert tray._status == TrayStatus.ERROR
        assert "Connection failed" in tray._status_text

    def test_set_conflict(self, tmp_path: Path) -> None:
        """Should set conflict status."""
        tray = SyncAgentTray(tmp_path)
        tray.set_conflict(3)
        assert tray._status == TrayStatus.CONFLICT
        assert "3" in tray._status_text

    def test_set_offline(self, tmp_path: Path) -> None:
        """Should set offline status."""
        tray = SyncAgentTray(tmp_path)
        tray.set_offline()
        assert tray._status == TrayStatus.OFFLINE

    def test_get_pause_text(self, tmp_path: Path) -> None:
        """Should return appropriate pause/resume text."""
        tray = SyncAgentTray(tmp_path)

        tray._paused = False
        assert "Pause" in tray._get_pause_text()

        tray._paused = True
        assert "Resume" in tray._get_pause_text()

    @patch("syncagent.client.tray.Icon")
    def test_start_creates_icon(self, mock_icon_class: MagicMock, tmp_path: Path) -> None:
        """Should create Icon instance on start."""
        mock_icon = MagicMock()
        mock_icon_class.return_value = mock_icon

        tray = SyncAgentTray(tmp_path)
        tray.start(blocking=False)

        mock_icon_class.assert_called_once()
        assert tray._icon is mock_icon

    @patch("syncagent.client.tray.Icon")
    def test_stop_stops_icon(self, mock_icon_class: MagicMock, tmp_path: Path) -> None:
        """Should stop the icon."""
        mock_icon = MagicMock()
        mock_icon_class.return_value = mock_icon

        tray = SyncAgentTray(tmp_path)
        tray.start(blocking=False)
        tray.stop()

        mock_icon.stop.assert_called_once()
        assert tray._icon is None

    @patch("syncagent.client.tray.Icon")
    def test_notify(self, mock_icon_class: MagicMock, tmp_path: Path) -> None:
        """Should send notification through icon."""
        mock_icon = MagicMock()
        mock_icon_class.return_value = mock_icon

        tray = SyncAgentTray(tmp_path)
        tray.start(blocking=False)
        tray.notify("Test Title", "Test Message")

        mock_icon.notify.assert_called_once_with("Test Message", "Test Title")

    def test_callback_on_sync_now(self, tmp_path: Path) -> None:
        """Should call sync_now callback."""
        callback = MagicMock()
        callbacks = TrayCallbacks(on_sync_now=callback)
        tray = SyncAgentTray(tmp_path, callbacks=callbacks)

        tray._on_sync_now()
        callback.assert_called_once()

    def test_callback_on_quit(self, tmp_path: Path) -> None:
        """Should call quit callback."""
        callback = MagicMock()
        callbacks = TrayCallbacks(on_quit=callback)
        tray = SyncAgentTray(tmp_path, callbacks=callbacks)

        with patch.object(tray, "stop"):
            tray._on_quit()
            callback.assert_called_once()

    def test_on_pause_resume_toggles(self, tmp_path: Path) -> None:
        """Should toggle paused state."""
        tray = SyncAgentTray(tmp_path)
        assert tray._paused is False

        tray._on_pause_resume()
        assert tray._paused is True

        tray._on_pause_resume()
        assert tray._paused is False


@pytest.mark.skipif(not PYSTRAY_AVAILABLE, reason="pystray not installed")
class TestRunTray:
    """Tests for run_tray helper function."""

    @patch("syncagent.client.tray.SyncAgentTray.start")
    def test_creates_and_starts_tray(self, mock_start: MagicMock, tmp_path: Path) -> None:
        """Should create tray and start in background."""
        tray = run_tray(tmp_path)

        assert isinstance(tray, SyncAgentTray)
        mock_start.assert_called_once_with(blocking=False)

    @patch("syncagent.client.tray.SyncAgentTray.start")
    def test_passes_parameters(self, mock_start: MagicMock, tmp_path: Path) -> None:
        """Should pass all parameters to SyncAgentTray."""
        callbacks = TrayCallbacks(on_quit=MagicMock())
        tray = run_tray(tmp_path, dashboard_url="http://test.com", callbacks=callbacks)

        assert tray._dashboard_url == "http://test.com"
        assert tray._callbacks.on_quit is not None


class TestPystrayAvailability:
    """Tests for pystray availability check."""

    def test_pystray_available_flag_exists(self) -> None:
        """Should have PYSTRAY_AVAILABLE flag."""
        assert isinstance(PYSTRAY_AVAILABLE, bool)

    @pytest.mark.skipif(PYSTRAY_AVAILABLE, reason="pystray is installed")
    def test_raises_import_error_without_pystray(self, tmp_path: Path) -> None:
        """Should raise ImportError if pystray not available."""
        with pytest.raises(ImportError, match="pystray"):
            SyncAgentTray(tmp_path)
