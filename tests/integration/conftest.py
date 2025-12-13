"""Pytest fixtures for integration tests.

This module provides fixtures for end-to-end testing with a real server
running in-memory with local filesystem storage.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Generator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest
import uvicorn
from httpx import Client

from syncagent.client.api import HTTPClient
from syncagent.client.state import LocalSyncState
from syncagent.client.sync import ChangeScanner, FileDownloader, FileUploader
from syncagent.core.config import ServerConfig
from syncagent.core.crypto import derive_key, generate_salt
from syncagent.server.app import create_app
from syncagent.server.database import Database
from syncagent.server.storage import LocalFSStorage


@dataclass
class TestServer:
    """Container for test server resources."""

    db: Database
    storage: LocalFSStorage
    url: str
    thread: threading.Thread

    def create_invitation(self) -> str:
        """Create an invitation token for machine registration."""
        raw_token, _ = self.db.create_invitation()
        return raw_token

    def stop(self) -> None:
        """Stop the server (best effort - uvicorn doesn't have clean shutdown)."""
        # The thread will be cleaned up when the test ends


@dataclass
class SyncTestClient:
    """Container for a simulated sync client."""

    name: str
    sync_folder: Path
    state: LocalSyncState
    api_client: HTTPClient
    encryption_key: bytes
    uploader: FileUploader
    downloader: FileDownloader
    scanner: ChangeScanner | None = None

    def create_file(self, relative_path: str, content: str | bytes) -> Path:
        """Create a file in the sync folder."""
        file_path = self.sync_folder / relative_path
        file_path.parent.mkdir(parents=True, exist_ok=True)
        if isinstance(content, str):
            file_path.write_text(content, encoding="utf-8")
        else:
            file_path.write_bytes(content)
        return file_path

    def read_file(self, relative_path: str) -> str:
        """Read a file from the sync folder."""
        return (self.sync_folder / relative_path).read_text(encoding="utf-8")

    def file_exists(self, relative_path: str) -> bool:
        """Check if a file exists in the sync folder."""
        return (self.sync_folder / relative_path).exists()


class UvicornTestServer:
    """Uvicorn server running in a background thread for testing."""

    def __init__(self, app: Any, host: str = "127.0.0.1", port: int = 0) -> None:
        self.app = app
        self.host = host
        self.port = port
        self.server: uvicorn.Server | None = None
        self.thread: threading.Thread | None = None

    def start(self) -> int:
        """Start the server and return the port."""
        # Find a free port
        import socket

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind((self.host, 0))
            self.port = s.getsockname()[1]

        config = uvicorn.Config(
            self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
        )
        self.server = uvicorn.Server(config)

        self.thread = threading.Thread(target=self.server.run, daemon=True)
        self.thread.start()

        # Wait for server to be ready
        self._wait_for_ready()

        return self.port

    def _wait_for_ready(self, timeout: float = 5.0) -> None:
        """Wait for the server to be ready to accept connections."""
        start = time.time()
        while time.time() - start < timeout:
            try:
                with Client() as client:
                    response = client.get(f"http://{self.host}:{self.port}/health")
                    if response.status_code == 200:
                        return
            except Exception:
                pass
            time.sleep(0.1)
        raise RuntimeError("Server failed to start in time")

    def stop(self) -> None:
        """Stop the server."""
        if self.server:
            self.server.should_exit = True


@pytest.fixture
def encryption_key() -> bytes:
    """Generate a shared encryption key for all test clients."""
    salt = generate_salt()
    return derive_key("integration-test-password", salt)


@pytest.fixture
def test_server(tmp_path: Path) -> Generator[TestServer, None, None]:
    """Create and start a test server with in-memory DB and local storage."""
    # Create database and storage
    db_path = tmp_path / "server" / "test.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path)

    storage_path = tmp_path / "server" / "chunks"
    storage = LocalFSStorage(storage_path)

    # Create FastAPI app
    app = create_app(db, storage)

    # Start server in background thread
    server = UvicornTestServer(app)
    port = server.start()
    url = f"http://127.0.0.1:{port}"

    yield TestServer(
        db=db,
        storage=storage,
        url=url,
        thread=server.thread,  # type: ignore
    )

    # Cleanup
    server.stop()
    db.close()


@pytest.fixture
def client_factory(
    tmp_path: Path,
    test_server: TestServer,
    encryption_key: bytes,
) -> Generator[Any, None, None]:
    """Factory fixture to create multiple test clients."""
    clients: list[SyncTestClient] = []
    client_counter = 0

    def _create_client(name: str | None = None) -> SyncTestClient:
        nonlocal client_counter
        client_counter += 1

        if name is None:
            name = f"test-client-{client_counter}"

        # Create sync folder for this client
        sync_folder = tmp_path / "clients" / name / "sync"
        sync_folder.mkdir(parents=True, exist_ok=True)

        # Create state database
        state_path = tmp_path / "clients" / name / "state.db"
        state = LocalSyncState(state_path)

        # Register machine with server
        invitation = test_server.create_invitation()
        with Client() as http_client:
            response = http_client.post(
                f"{test_server.url}/api/machines/register",
                json={
                    "name": name,
                    "platform": "test",
                    "invitation_token": invitation,
                },
            )
            response.raise_for_status()
            data = response.json()
            token = data["token"]

        # Create API client
        config = ServerConfig(server_url=test_server.url, token=token)
        api_client = HTTPClient(config)

        # Create uploader and downloader
        uploader = FileUploader(api_client, encryption_key)
        downloader = FileDownloader(api_client, encryption_key)

        client = SyncTestClient(
            name=name,
            sync_folder=sync_folder,
            state=state,
            api_client=api_client,
            encryption_key=encryption_key,
            uploader=uploader,
            downloader=downloader,
        )
        clients.append(client)
        return client

    yield _create_client

    # Cleanup
    for client in clients:
        client.state.close()
        client.api_client.close()


@pytest.fixture
def client_a(client_factory: Any) -> SyncTestClient:
    """Create first test client (client A)."""
    return client_factory("client-a")


@pytest.fixture
def client_b(client_factory: Any) -> SyncTestClient:
    """Create second test client (client B)."""
    return client_factory("client-b")
