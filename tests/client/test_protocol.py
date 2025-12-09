"""Tests for protocol handler module."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from syncagent.client.protocol import (
    InvalidURLError,
    RegistrationError,
    SecurityError,
    SyncFileURL,
    handle_url,
    is_registered,
    open_file,
    register_protocol,
    resolve_file_path,
    unregister_protocol,
    validate_path,
)


class TestSyncFileURL:
    """Tests for URL parsing."""

    def test_parse_valid_url(self) -> None:
        """Should parse a valid syncfile:// URL."""
        url = "syncfile://open?path=docs/readme.txt"
        parsed = SyncFileURL.parse(url)

        assert parsed.action == "open"
        assert parsed.path == "docs/readme.txt"
        assert parsed.raw_url == url

    def test_parse_url_with_spaces(self) -> None:
        """Should handle URL-encoded spaces."""
        url = "syncfile://open?path=my%20documents/file.txt"
        parsed = SyncFileURL.parse(url)

        assert parsed.path == "my documents/file.txt"

    def test_parse_url_with_special_chars(self) -> None:
        """Should handle URL-encoded special characters."""
        url = "syncfile://open?path=docs%2Fsubdir%2Ffile.txt"
        parsed = SyncFileURL.parse(url)

        assert parsed.path == "docs/subdir/file.txt"

    def test_parse_empty_url(self) -> None:
        """Should reject empty URL."""
        with pytest.raises(InvalidURLError, match="cannot be empty"):
            SyncFileURL.parse("")

    def test_parse_wrong_scheme(self) -> None:
        """Should reject non-syncfile scheme."""
        with pytest.raises(InvalidURLError, match="Invalid scheme"):
            SyncFileURL.parse("http://open?path=file.txt")

    def test_parse_missing_action(self) -> None:
        """Should reject URL without action."""
        with pytest.raises(InvalidURLError, match="Missing action"):
            SyncFileURL.parse("syncfile://?path=file.txt")

    def test_parse_missing_path(self) -> None:
        """Should reject URL without path parameter."""
        with pytest.raises(InvalidURLError, match="Missing 'path'"):
            SyncFileURL.parse("syncfile://open")

    def test_parse_missing_path_value(self) -> None:
        """Should reject URL with empty path."""
        with pytest.raises(InvalidURLError, match="Missing 'path'"):
            SyncFileURL.parse("syncfile://open?other=value")


class TestValidatePath:
    """Tests for path validation."""

    def test_valid_simple_path(self) -> None:
        """Should accept simple relative path."""
        result = validate_path("docs/file.txt")
        assert result == "docs/file.txt"

    def test_valid_nested_path(self) -> None:
        """Should accept deeply nested path."""
        result = validate_path("a/b/c/d/file.txt")
        assert result == "a/b/c/d/file.txt"

    def test_normalize_backslashes(self) -> None:
        """Should normalize Windows backslashes."""
        result = validate_path("docs\\subdir\\file.txt")
        assert result == "docs/subdir/file.txt"

    def test_reject_parent_directory(self) -> None:
        """Should reject path with parent directory reference."""
        with pytest.raises(SecurityError, match="Path traversal"):
            validate_path("docs/../etc/passwd")

    def test_reject_double_dots_middle(self) -> None:
        """Should reject .. in middle of path."""
        with pytest.raises(SecurityError, match="Path traversal"):
            validate_path("a/b/../c/file.txt")

    def test_reject_absolute_unix(self) -> None:
        """Should handle leading slash (results in relative path)."""
        result = validate_path("/docs/file.txt")
        assert result == "docs/file.txt"

    def test_reject_absolute_windows(self) -> None:
        """Should reject Windows absolute path."""
        with pytest.raises(SecurityError, match="Absolute paths"):
            validate_path("C:/docs/file.txt")

    def test_reject_empty_path(self) -> None:
        """Should reject empty path."""
        with pytest.raises(SecurityError, match="cannot be empty"):
            validate_path("")

    def test_strip_leading_dot_slash(self) -> None:
        """Should handle leading ./."""
        result = validate_path("./docs/file.txt")
        assert result == "docs/file.txt"

    def test_reject_only_dots(self) -> None:
        """Should reject path of only dots."""
        with pytest.raises(SecurityError, match="Path traversal"):
            validate_path("..")


class TestResolveFilePath:
    """Tests for path resolution."""

    def test_resolve_valid_path(self, tmp_path: Path) -> None:
        """Should resolve valid relative path."""
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        test_file = sync_folder / "docs" / "file.txt"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        result = resolve_file_path(sync_folder, "docs/file.txt")
        assert result == test_file.resolve()

    def test_reject_escape_attempt(self, tmp_path: Path) -> None:
        """Should reject path that escapes sync folder."""
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        with pytest.raises(SecurityError, match="Path traversal"):
            resolve_file_path(sync_folder, "../outside.txt")

    def test_resolve_with_symlink_escape(self, tmp_path: Path) -> None:
        """Should reject symlink that escapes sync folder."""
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        # Create a file outside sync folder
        outside_file = tmp_path / "secret.txt"
        outside_file.write_text("secret")

        # Create symlink inside sync folder pointing outside
        symlink = sync_folder / "link.txt"
        try:
            symlink.symlink_to(outside_file)
        except OSError:
            pytest.skip("Symlinks not supported on this system")

        # The resolved path should fail validation
        with pytest.raises(SecurityError, match="escapes sync folder"):
            resolve_file_path(sync_folder, "link.txt")


class TestOpenFile:
    """Tests for file opening."""

    def test_open_nonexistent_file(self, tmp_path: Path) -> None:
        """Should raise error for nonexistent file."""
        with pytest.raises(FileNotFoundError):
            open_file(tmp_path / "nonexistent.txt")

    @patch("syncagent.client.protocol.platform.system", return_value="Windows")
    @patch("syncagent.client.protocol.os.startfile")
    def test_open_file_windows(
        self, mock_startfile: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use os.startfile on Windows."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        open_file(test_file)

        mock_startfile.assert_called_once_with(str(test_file))

    @patch("syncagent.client.protocol.platform.system", return_value="Darwin")
    @patch("syncagent.client.protocol.subprocess.run")
    def test_open_file_macos(
        self, mock_run: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use 'open' command on macOS."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        open_file(test_file)

        mock_run.assert_called_once_with(["open", str(test_file)], check=True)

    @patch("syncagent.client.protocol.platform.system", return_value="Linux")
    @patch("syncagent.client.protocol.subprocess.run")
    def test_open_file_linux(
        self, mock_run: MagicMock, mock_system: MagicMock, tmp_path: Path
    ) -> None:
        """Should use 'xdg-open' command on Linux."""
        test_file = tmp_path / "file.txt"
        test_file.write_text("content")

        open_file(test_file)

        mock_run.assert_called_once_with(["xdg-open", str(test_file)], check=True)


class TestHandleURL:
    """Tests for URL handling."""

    @patch("syncagent.client.protocol.open_file")
    def test_handle_open_action(
        self, mock_open: MagicMock, tmp_path: Path
    ) -> None:
        """Should open file for 'open' action."""
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()
        test_file = sync_folder / "docs" / "file.txt"
        test_file.parent.mkdir(parents=True)
        test_file.write_text("content")

        result = handle_url("syncfile://open?path=docs/file.txt", sync_folder)

        assert result == test_file.resolve()
        mock_open.assert_called_once()

    def test_handle_unknown_action(self, tmp_path: Path) -> None:
        """Should reject unknown action."""
        with pytest.raises(ValueError, match="Unknown action"):
            handle_url("syncfile://unknown?path=file.txt", tmp_path)

    def test_handle_file_not_found(self, tmp_path: Path) -> None:
        """Should raise error if file doesn't exist."""
        sync_folder = tmp_path / "sync"
        sync_folder.mkdir()

        with pytest.raises(FileNotFoundError):
            handle_url("syncfile://open?path=nonexistent.txt", sync_folder)


class TestProtocolRegistration:
    """Tests for protocol registration."""

    @patch("syncagent.client.protocol.platform.system", return_value="Windows")
    @patch("syncagent.client.protocol.register_windows")
    def test_register_windows(
        self, mock_register: MagicMock, mock_system: MagicMock
    ) -> None:
        """Should call Windows registration on Windows."""
        register_protocol()
        mock_register.assert_called_once()

    @patch("syncagent.client.protocol.platform.system", return_value="Darwin")
    @patch("syncagent.client.protocol.register_macos")
    def test_register_macos(
        self, mock_register: MagicMock, mock_system: MagicMock
    ) -> None:
        """Should call macOS registration on Darwin."""
        register_protocol()
        mock_register.assert_called_once()

    @patch("syncagent.client.protocol.platform.system", return_value="Linux")
    @patch("syncagent.client.protocol.register_linux")
    def test_register_linux(
        self, mock_register: MagicMock, mock_system: MagicMock
    ) -> None:
        """Should call Linux registration on Linux."""
        register_protocol()
        mock_register.assert_called_once()

    @patch("syncagent.client.protocol.platform.system", return_value="FreeBSD")
    def test_register_unsupported(self, mock_system: MagicMock) -> None:
        """Should raise error on unsupported platform."""
        with pytest.raises(RegistrationError, match="Unsupported platform"):
            register_protocol()

    @patch("syncagent.client.protocol.platform.system", return_value="Windows")
    @patch("syncagent.client.protocol.unregister_windows")
    def test_unregister_windows(
        self, mock_unregister: MagicMock, mock_system: MagicMock
    ) -> None:
        """Should call Windows unregistration on Windows."""
        unregister_protocol()
        mock_unregister.assert_called_once()


class TestIsRegistered:
    """Tests for registration check."""

    @patch("syncagent.client.protocol.platform.system", return_value="Linux")
    def test_not_registered_linux(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """Should return False when not registered on Linux."""
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_registered() is False

    @patch("syncagent.client.protocol.platform.system", return_value="Darwin")
    def test_not_registered_macos(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """Should return False when not registered on macOS."""
        with patch.object(Path, "home", return_value=tmp_path):
            assert is_registered() is False

    @patch("syncagent.client.protocol.platform.system", return_value="Linux")
    def test_registered_linux(self, mock_system: MagicMock, tmp_path: Path) -> None:
        """Should return True when registered on Linux."""
        # Create the desktop file
        apps_dir = tmp_path / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True)
        desktop_file = apps_dir / "syncfile-handler.desktop"
        desktop_file.write_text("[Desktop Entry]")

        with patch.object(Path, "home", return_value=tmp_path):
            assert is_registered() is True
