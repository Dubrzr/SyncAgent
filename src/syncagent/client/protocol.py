"""Protocol handler for syncfile:// URLs.

This module provides:
- URL parsing and validation for syncfile:// scheme
- Platform-specific protocol registration (Windows, macOS, Linux)
- Security validation to prevent path traversal attacks
- File opening functionality

URL Format:
    syncfile://open?path=relative/path/to/file.txt

Security:
    - Path traversal prevention (no .. components)
    - URL decoding with validation
    - Restricted to sync folder only
"""

from __future__ import annotations

import os
import platform
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse


class ProtocolError(Exception):
    """Base exception for protocol handler errors."""


class InvalidURLError(ProtocolError):
    """Raised when URL format is invalid."""


class SecurityError(ProtocolError):
    """Raised when security validation fails."""


class RegistrationError(ProtocolError):
    """Raised when protocol registration fails."""


@dataclass
class SyncFileURL:
    """Parsed syncfile:// URL.

    Attributes:
        action: The action to perform (e.g., "open")
        path: The relative file path within the sync folder
        raw_url: The original URL string
    """

    action: str
    path: str
    raw_url: str

    @classmethod
    def parse(cls, url: str) -> SyncFileURL:
        """Parse a syncfile:// URL.

        Args:
            url: The URL to parse (e.g., "syncfile://open?path=docs/file.txt")

        Returns:
            Parsed SyncFileURL object

        Raises:
            InvalidURLError: If URL format is invalid
        """
        if not url:
            raise InvalidURLError("URL cannot be empty")

        parsed = urlparse(url)

        # Validate scheme
        if parsed.scheme != "syncfile":
            raise InvalidURLError(f"Invalid scheme: {parsed.scheme}, expected 'syncfile'")

        # Get action from netloc (host part)
        action = parsed.netloc
        if not action:
            raise InvalidURLError("Missing action in URL")

        # Parse query parameters
        query_params = parse_qs(parsed.query)

        # Get path parameter
        path_list = query_params.get("path", [])
        if not path_list:
            raise InvalidURLError("Missing 'path' parameter")

        # URL decode the path
        path = unquote(path_list[0])

        return cls(action=action, path=path, raw_url=url)


def validate_path(path: str) -> str:
    """Validate and sanitize a file path for security.

    Prevents path traversal attacks and ensures the path stays within
    the sync folder.

    Args:
        path: The path to validate

    Returns:
        Sanitized path string

    Raises:
        SecurityError: If path contains dangerous components
    """
    if not path:
        raise SecurityError("Path cannot be empty")

    # Normalize path separators
    normalized = path.replace("\\", "/")

    # Split into components
    parts = normalized.split("/")

    # Check each component
    sanitized_parts: list[str] = []
    for part in parts:
        # Skip empty parts (from leading/trailing slashes)
        if not part:
            continue

        # Block parent directory references
        if part == "..":
            raise SecurityError("Path traversal detected: '..' not allowed")

        # Block absolute path indicators
        if part == "." and not sanitized_parts:
            continue  # Allow leading ./ but ignore it

        # Block hidden files on Unix (optional, can be configured)
        # if part.startswith("."):
        #     raise SecurityError(f"Hidden files not allowed: {part}")

        # Block Windows drive letters
        if len(part) == 2 and part[1] == ":" and part[0].isalpha():
            raise SecurityError("Absolute paths not allowed")

        sanitized_parts.append(part)

    if not sanitized_parts:
        raise SecurityError("Path resolves to empty")

    return "/".join(sanitized_parts)


def resolve_file_path(sync_folder: Path, relative_path: str) -> Path:
    """Resolve a relative path to an absolute path within the sync folder.

    Args:
        sync_folder: The base sync folder path
        relative_path: The relative path from the URL

    Returns:
        Absolute path to the file

    Raises:
        SecurityError: If resolved path escapes sync folder
        FileNotFoundError: If file doesn't exist
    """
    # Validate the relative path first
    safe_path = validate_path(relative_path)

    # Resolve to absolute path
    absolute_path = (sync_folder / safe_path).resolve()

    # Ensure it's still within sync folder (defense in depth)
    try:
        absolute_path.relative_to(sync_folder.resolve())
    except ValueError as e:
        raise SecurityError(
            f"Path escapes sync folder: {relative_path}"
        ) from e

    return absolute_path


def open_file(file_path: Path) -> None:
    """Open a file with the system's default application.

    Args:
        file_path: Path to the file to open

    Raises:
        FileNotFoundError: If file doesn't exist
        OSError: If file cannot be opened
    """
    if not file_path.exists():
        raise FileNotFoundError(f"File not found: {file_path}")

    system = platform.system()

    if system == "Windows":
        os.startfile(str(file_path))  # type: ignore[attr-defined]
    elif system == "Darwin":  # macOS
        subprocess.run(["open", str(file_path)], check=True)
    else:  # Linux and others
        subprocess.run(["xdg-open", str(file_path)], check=True)


def handle_url(url: str, sync_folder: Path) -> Path:
    """Handle a syncfile:// URL.

    Parses the URL, validates security, and performs the requested action.

    Args:
        url: The syncfile:// URL to handle
        sync_folder: The base sync folder path

    Returns:
        The resolved file path

    Raises:
        InvalidURLError: If URL format is invalid
        SecurityError: If security validation fails
        FileNotFoundError: If file doesn't exist
        ValueError: If action is not supported
    """
    parsed = SyncFileURL.parse(url)

    if parsed.action == "open":
        file_path = resolve_file_path(sync_folder, parsed.path)

        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {parsed.path}")

        open_file(file_path)
        return file_path

    raise ValueError(f"Unknown action: {parsed.action}")


# =============================================================================
# Platform-specific protocol registration
# =============================================================================


def _get_executable_path() -> str:
    """Get the path to the syncagent executable."""
    # If running as installed package, use the entry point
    if getattr(sys, "frozen", False):
        # Running as compiled executable (PyInstaller, etc.)
        return sys.executable

    # Running as Python script - use the module
    return f'"{sys.executable}" -m syncagent.client.cli'


def register_windows() -> None:
    """Register syncfile:// protocol handler on Windows.

    Creates registry entries to associate syncfile:// URLs with syncagent.

    Raises:
        RegistrationError: If registration fails
    """
    if platform.system() != "Windows":
        raise RegistrationError("Windows registration only works on Windows")

    try:
        import winreg  # type: ignore[import-not-found]

        exe_path = _get_executable_path()
        command = f'{exe_path} open-url "%1"'

        # Create HKEY_CURRENT_USER\Software\Classes\syncfile
        key_path = r"Software\Classes\syncfile"

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:  # type: ignore[attr-defined]
            winreg.SetValue(key, "", winreg.REG_SZ, "URL:SyncFile Protocol")  # type: ignore[attr-defined]
            winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")  # type: ignore[attr-defined]

        # Create shell\open\command subkey
        command_path = rf"{key_path}\shell\open\command"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:  # type: ignore[attr-defined]
            winreg.SetValue(key, "", winreg.REG_SZ, command)  # type: ignore[attr-defined]

        # Create DefaultIcon subkey (optional)
        icon_path = rf"{key_path}\DefaultIcon"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, icon_path) as key:  # type: ignore[attr-defined]
            # Use Python icon as default
            winreg.SetValue(key, "", winreg.REG_SZ, f"{sys.executable},0")  # type: ignore[attr-defined]

    except Exception as e:
        raise RegistrationError(f"Failed to register on Windows: {e}") from e


def unregister_windows() -> None:
    """Unregister syncfile:// protocol handler on Windows.

    Raises:
        RegistrationError: If unregistration fails
    """
    if platform.system() != "Windows":
        raise RegistrationError("Windows unregistration only works on Windows")

    try:
        import winreg  # type: ignore[import-not-found]

        key_path = r"Software\Classes\syncfile"

        # Delete subkeys first (registry requires this)
        def delete_key_recursive(root: int, path: str) -> None:
            try:
                with winreg.OpenKey(root, path, 0, winreg.KEY_ALL_ACCESS) as key:  # type: ignore[attr-defined]
                    while True:
                        try:
                            subkey = winreg.EnumKey(key, 0)  # type: ignore[attr-defined]
                            delete_key_recursive(root, f"{path}\\{subkey}")
                        except OSError:
                            break
                winreg.DeleteKey(root, path)  # type: ignore[attr-defined]
            except FileNotFoundError:
                pass  # Key doesn't exist

        delete_key_recursive(winreg.HKEY_CURRENT_USER, key_path)  # type: ignore[attr-defined]

    except Exception as e:
        raise RegistrationError(f"Failed to unregister on Windows: {e}") from e


def register_macos() -> None:
    """Register syncfile:// protocol handler on macOS.

    Creates a LaunchServices entry via Info.plist modification or
    a helper application.

    Note: Full macOS registration requires an application bundle.
    This provides a simpler approach using a helper script.

    Raises:
        RegistrationError: If registration fails
    """
    if platform.system() != "Darwin":
        raise RegistrationError("macOS registration only works on macOS")

    try:
        # Create handler script in ~/Library/Application Support/SyncAgent/
        support_dir = Path.home() / "Library" / "Application Support" / "SyncAgent"
        support_dir.mkdir(parents=True, exist_ok=True)

        handler_script = support_dir / "url_handler.sh"
        exe_path = _get_executable_path()

        script_content = f"""#!/bin/bash
# SyncFile URL Handler
{exe_path} open-url "$1"
"""
        handler_script.write_text(script_content)
        handler_script.chmod(0o755)

        # Create a minimal .app bundle for URL handling
        app_dir = support_dir / "SyncFileHandler.app" / "Contents"
        app_dir.mkdir(parents=True, exist_ok=True)

        macos_dir = app_dir / "MacOS"
        macos_dir.mkdir(exist_ok=True)

        # Create the executable
        app_script = macos_dir / "SyncFileHandler"
        app_script.write_text(f"""#!/bin/bash
{exe_path} open-url "$1"
""")
        app_script.chmod(0o755)

        # Create Info.plist
        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleExecutable</key>
    <string>SyncFileHandler</string>
    <key>CFBundleIdentifier</key>
    <string>com.syncagent.urlhandler</string>
    <key>CFBundleName</key>
    <string>SyncFile Handler</string>
    <key>CFBundlePackageType</key>
    <string>APPL</string>
    <key>CFBundleShortVersionString</key>
    <string>1.0</string>
    <key>CFBundleURLTypes</key>
    <array>
        <dict>
            <key>CFBundleURLName</key>
            <string>SyncFile URL</string>
            <key>CFBundleURLSchemes</key>
            <array>
                <string>syncfile</string>
            </array>
        </dict>
    </array>
    <key>LSBackgroundOnly</key>
    <true/>
</dict>
</plist>
"""
        plist_file = app_dir / "Info.plist"
        plist_file.write_text(plist_content)

        # Register the handler with Launch Services
        app_path = support_dir / "SyncFileHandler.app"
        subprocess.run(
            ["/System/Library/Frameworks/CoreServices.framework/Frameworks/"
             "LaunchServices.framework/Support/lsregister",
             "-f", str(app_path)],
            check=True,
            capture_output=True,
        )

    except subprocess.CalledProcessError as e:
        raise RegistrationError(f"Failed to register with LaunchServices: {e}") from e
    except Exception as e:
        raise RegistrationError(f"Failed to register on macOS: {e}") from e


def unregister_macos() -> None:
    """Unregister syncfile:// protocol handler on macOS.

    Raises:
        RegistrationError: If unregistration fails
    """
    if platform.system() != "Darwin":
        raise RegistrationError("macOS unregistration only works on macOS")

    try:
        import shutil

        support_dir = Path.home() / "Library" / "Application Support" / "SyncAgent"
        app_path = support_dir / "SyncFileHandler.app"

        if app_path.exists():
            # Unregister from Launch Services
            subprocess.run(
                ["/System/Library/Frameworks/CoreServices.framework/Frameworks/"
                 "LaunchServices.framework/Support/lsregister",
                 "-u", str(app_path)],
                check=False,  # Don't fail if not registered
                capture_output=True,
            )

            # Remove the app bundle
            shutil.rmtree(app_path)

        # Remove handler script
        handler_script = support_dir / "url_handler.sh"
        if handler_script.exists():
            handler_script.unlink()

    except Exception as e:
        raise RegistrationError(f"Failed to unregister on macOS: {e}") from e


def register_linux() -> None:
    """Register syncfile:// protocol handler on Linux.

    Creates a .desktop file and registers it with xdg-mime.

    Raises:
        RegistrationError: If registration fails
    """
    if platform.system() != "Linux":
        raise RegistrationError("Linux registration only works on Linux")

    try:
        # Create .desktop file in ~/.local/share/applications/
        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)

        exe_path = _get_executable_path()

        desktop_content = f"""[Desktop Entry]
Type=Application
Name=SyncFile Handler
Comment=Handle syncfile:// URLs
Exec={exe_path} open-url %u
Terminal=false
NoDisplay=true
MimeType=x-scheme-handler/syncfile;
Categories=Utility;
"""
        desktop_file = apps_dir / "syncfile-handler.desktop"
        desktop_file.write_text(desktop_content)

        # Register as default handler for syncfile:// scheme
        subprocess.run(
            ["xdg-mime", "default", "syncfile-handler.desktop",
             "x-scheme-handler/syncfile"],
            check=True,
            capture_output=True,
        )

        # Update desktop database
        subprocess.run(
            ["update-desktop-database", str(apps_dir)],
            check=False,  # May not be available on all systems
            capture_output=True,
        )

    except subprocess.CalledProcessError as e:
        raise RegistrationError(f"Failed to register with xdg-mime: {e}") from e
    except Exception as e:
        raise RegistrationError(f"Failed to register on Linux: {e}") from e


def unregister_linux() -> None:
    """Unregister syncfile:// protocol handler on Linux.

    Raises:
        RegistrationError: If unregistration fails
    """
    if platform.system() != "Linux":
        raise RegistrationError("Linux unregistration only works on Linux")

    try:
        apps_dir = Path.home() / ".local" / "share" / "applications"
        desktop_file = apps_dir / "syncfile-handler.desktop"

        if desktop_file.exists():
            desktop_file.unlink()

            # Update desktop database
            subprocess.run(
                ["update-desktop-database", str(apps_dir)],
                check=False,
                capture_output=True,
            )

    except Exception as e:
        raise RegistrationError(f"Failed to unregister on Linux: {e}") from e


def register_protocol() -> None:
    """Register syncfile:// protocol handler for the current platform.

    Raises:
        RegistrationError: If registration fails or platform not supported
    """
    system = platform.system()

    if system == "Windows":
        register_windows()
    elif system == "Darwin":
        register_macos()
    elif system == "Linux":
        register_linux()
    else:
        raise RegistrationError(f"Unsupported platform: {system}")


def unregister_protocol() -> None:
    """Unregister syncfile:// protocol handler for the current platform.

    Raises:
        RegistrationError: If unregistration fails or platform not supported
    """
    system = platform.system()

    if system == "Windows":
        unregister_windows()
    elif system == "Darwin":
        unregister_macos()
    elif system == "Linux":
        unregister_linux()
    else:
        raise RegistrationError(f"Unsupported platform: {system}")


def is_registered() -> bool:
    """Check if syncfile:// protocol handler is registered.

    Returns:
        True if registered, False otherwise
    """
    system = platform.system()

    try:
        if system == "Windows":
            import winreg  # type: ignore[import-not-found]

            try:
                with winreg.OpenKey(  # type: ignore[attr-defined]
                    winreg.HKEY_CURRENT_USER,  # type: ignore[attr-defined]
                    r"Software\Classes\syncfile\shell\open\command"
                ):
                    return True
            except FileNotFoundError:
                return False

        elif system == "Darwin":
            app_path = (
                Path.home() / "Library" / "Application Support" /
                "SyncAgent" / "SyncFileHandler.app"
            )
            return app_path.exists()

        elif system == "Linux":
            desktop_file = (
                Path.home() / ".local" / "share" / "applications" /
                "syncfile-handler.desktop"
            )
            return desktop_file.exists()

        return False

    except Exception:
        return False
