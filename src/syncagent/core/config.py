"""Shared configuration classes for syncagent.

This module defines configuration classes used by both client and server components.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class ServerConfig:
    """Configuration for connecting to a SyncAgent server.

    Used by both HTTP client (SyncClient) and WebSocket client (StatusReporter)
    to ensure consistent connection settings.

    Attributes:
        server_url: Base URL of the server (e.g., "https://sync.example.com").
        token: Authentication token for the machine.
        timeout: Request/connection timeout in seconds.
        verify_ssl: Whether to verify SSL certificates (default True).
    """

    server_url: str
    token: str
    timeout: float = 30.0
    verify_ssl: bool = True

    def __post_init__(self) -> None:
        """Normalize server URL."""
        self.server_url = self.server_url.rstrip("/")

    @property
    def ws_url(self) -> str:
        """Get WebSocket URL for status reporting.

        Returns:
            WebSocket URL with token in path.
        """
        url = self.server_url
        if url.startswith("https://"):
            url = "wss://" + url[8:]
        elif url.startswith("http://"):
            url = "ws://" + url[7:]
        return f"{url}/ws/client/{self.token}"

    @property
    def is_secure(self) -> bool:
        """Check if using HTTPS/WSS.

        Returns:
            True if server uses HTTPS.>
        """
        return self.server_url.startswith("https://")
