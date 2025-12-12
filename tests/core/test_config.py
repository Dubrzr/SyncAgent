"""Tests for core configuration classes."""

from __future__ import annotations

from syncagent.core.config import ServerConfig


class TestServerConfig:
    """Tests for ServerConfig class."""

    def test_init_basic(self) -> None:
        """Should initialize with required fields."""
        config = ServerConfig(server_url="https://example.com", token="test-token")
        assert config.server_url == "https://example.com"
        assert config.token == "test-token"
        assert config.timeout == 30.0
        assert config.verify_ssl is True

    def test_init_custom_timeout(self) -> None:
        """Should accept custom timeout."""
        config = ServerConfig(
            server_url="https://example.com",
            token="test-token",
            timeout=60.0,
        )
        assert config.timeout == 60.0

    def test_init_verify_ssl_false(self) -> None:
        """Should accept verify_ssl=False."""
        config = ServerConfig(
            server_url="https://example.com",
            token="test-token",
            verify_ssl=False,
        )
        assert config.verify_ssl is False

    def test_url_trailing_slash_removed(self) -> None:
        """Should strip trailing slash from server URL."""
        config = ServerConfig(server_url="https://example.com/", token="test-token")
        assert config.server_url == "https://example.com"

    def test_ws_url_https(self) -> None:
        """Should convert HTTPS to WSS for WebSocket URL."""
        config = ServerConfig(server_url="https://example.com", token="test-token")
        assert config.ws_url == "wss://example.com/ws/client/test-token"

    def test_ws_url_http(self) -> None:
        """Should convert HTTP to WS for WebSocket URL."""
        config = ServerConfig(server_url="http://localhost:8000", token="test-token")
        assert config.ws_url == "ws://localhost:8000/ws/client/test-token"

    def test_is_secure_https(self) -> None:
        """Should return True for HTTPS URLs."""
        config = ServerConfig(server_url="https://example.com", token="test-token")
        assert config.is_secure is True

    def test_is_secure_http(self) -> None:
        """Should return False for HTTP URLs."""
        config = ServerConfig(server_url="http://localhost:8000", token="test-token")
        assert config.is_secure is False
