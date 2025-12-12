"""FastAPI application for SyncAgent server.

This module creates and configures the FastAPI application with:
- REST API for machines, files, trash, and chunk storage
- Web UI for admin dashboard

Usage:
    uvicorn syncagent.server.app:app --host 0.0.0.0 --port 8000
"""

from __future__ import annotations

import logging
import os
import sys
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI

from syncagent.server.api.router import router as api_router
from syncagent.server.database import Database
from syncagent.server.storage import ChunkStorage, create_storage
from syncagent.server.web import router as web_router

# Configuration from environment variables with defaults
DB_PATH = Path(os.environ.get("SYNCAGENT_DB_PATH", "syncagent.db"))
LOG_PATH = Path(os.environ.get("SYNCAGENT_LOG_PATH", "syncagent-server.log"))


def _build_storage_config() -> dict[str, str | None]:
    """Build storage configuration from environment variables."""
    # S3 storage if bucket is configured
    s3_bucket = os.environ.get("SYNCAGENT_S3_BUCKET")
    if s3_bucket:
        return {
            "type": "s3",
            "bucket": s3_bucket,
            "endpoint_url": os.environ.get("SYNCAGENT_S3_ENDPOINT"),
            "access_key": os.environ.get("SYNCAGENT_S3_ACCESS_KEY"),
            "secret_key": os.environ.get("SYNCAGENT_S3_SECRET_KEY"),
            "region": os.environ.get("SYNCAGENT_S3_REGION", "us-east-1"),
        }

    # Local storage (default)
    return {
        "type": "local",
        "local_path": os.environ.get("SYNCAGENT_STORAGE_PATH", "storage"),
    }


STORAGE_CONFIG = _build_storage_config()


def setup_logging(log_path: Path) -> None:
    """Configure logging to output to both file and stdout.

    Args:
        log_path: Path to the log file.
    """
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    formatter = logging.Formatter(log_format)

    # Root logger for syncagent
    root_logger = logging.getLogger("syncagent")
    root_logger.setLevel(logging.INFO)

    # Stdout handler
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(formatter)
    root_logger.addHandler(stdout_handler)

    # File handler
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    root_logger.addHandler(file_handler)

    # Also capture uvicorn logs to file
    for uvicorn_name in ("uvicorn", "uvicorn.error", "uvicorn.access"):
        uvicorn_logger = logging.getLogger(uvicorn_name)
        uvicorn_logger.addHandler(file_handler)


setup_logging(LOG_PATH)
logger = logging.getLogger(__name__)


def create_app(db: Database, storage: ChunkStorage | None = None) -> FastAPI:
    """Create FastAPI application with custom database and storage.

    This is primarily used for testing with isolated databases.

    Args:
        db: Database instance.
        storage: Optional ChunkStorage instance.

    Returns:
        Configured FastAPI application.
    """

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
        """Application lifespan handler for startup/shutdown."""
        # Startup
        db_path = getattr(db, "_db_path", "in-memory")
        logger.info("=" * 60)
        logger.info("SyncAgent Server Starting")
        logger.info("=" * 60)
        logger.info("  Database: %s", db_path)
        if storage:
            logger.info("  Storage:  %s", storage.location)
        else:
            logger.info("  Storage:  None (storage disabled)")
        logger.info("  Logs:     %s", LOG_PATH.absolute())
        logger.info("=" * 60)

        yield

        # Shutdown
        logger.info("SyncAgent Server shutting down")

    application = FastAPI(
        title="SyncAgent Server",
        description="Zero-Knowledge E2EE File Sync Server",
        version="0.1.0",
        lifespan=lifespan,
    )

    application.state.db = db
    application.state.storage = storage

    application.include_router(api_router)
    application.include_router(web_router)

    return application


def app_factory() -> FastAPI:
    """Factory function for uvicorn --factory mode."""
    return create_app(
        db=Database(DB_PATH),
        storage=create_storage(STORAGE_CONFIG),
    )


# Default application instance for uvicorn
app = create_app(
    db=Database(DB_PATH),
    storage=create_storage(STORAGE_CONFIG),
)
