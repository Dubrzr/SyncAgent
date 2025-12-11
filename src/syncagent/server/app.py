"""FastAPI application for SyncAgent server.

This module creates and configures the FastAPI application with:
- REST API for machines, files, trash, and chunk storage
- Web UI for admin dashboard

Usage:
    uvicorn syncagent.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI

from syncagent.server.api.router import router as api_router
from syncagent.server.database import Database
from syncagent.server.storage import ChunkStorage, create_storage
from syncagent.server.web import router as web_router

# Configuration - can be overridden via environment variables
DB_PATH = Path("syncagent.db")
STORAGE_CONFIG: dict[str, str | None] = {"type": "local", "local_path": "storage"}


def create_app(db: Database, storage: ChunkStorage | None = None) -> FastAPI:
    """Create FastAPI application with custom database and storage.

    This is primarily used for testing with isolated databases.

    Args:
        db: Database instance.
        storage: Optional ChunkStorage instance.

    Returns:
        Configured FastAPI application.
    """
    application = FastAPI(
        title="SyncAgent Server",
        description="Zero-Knowledge E2EE File Sync Server",
        version="0.1.0",
    )

    application.state.db = db
    application.state.storage = storage

    application.include_router(api_router)
    application.include_router(web_router)

    return application


# Default application instance for uvicorn
app = create_app(
    db=Database(DB_PATH),
    storage=create_storage(STORAGE_CONFIG),
)
