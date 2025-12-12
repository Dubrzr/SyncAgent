"""Admin API routes for server management.

These endpoints require admin authentication (session cookie).
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, HTTPException, Request
from pydantic import BaseModel

from syncagent.server.database import Database
from syncagent.server.scheduler import purge_trash_with_storage
from syncagent.server.storage import ChunkStorage

router = APIRouter(prefix="/api/admin", tags=["admin"])


def get_db(request: Request) -> Database:
    """Get database from app state."""
    db: Database = request.app.state.db
    return db


def get_storage(request: Request) -> ChunkStorage | None:
    """Get chunk storage from app state (may be None)."""
    storage: ChunkStorage | None = request.app.state.storage
    return storage


def get_trash_retention_days(request: Request) -> int:
    """Get trash retention days from app state."""
    days: int = request.app.state.trash_retention_days
    return days


async def require_admin_session(
    request: Request,
    session: Annotated[str | None, Cookie()] = None,
) -> str:
    """Require a valid admin session.

    Returns:
        The admin username.

    Raises:
        HTTPException: If not authenticated.
    """
    if not session:
        raise HTTPException(status_code=401, detail="Not authenticated")

    db = get_db(request)
    session_obj = db.validate_session(session)

    if not session_obj:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    admin = db.get_admin()
    if not admin:
        raise HTTPException(status_code=401, detail="No admin configured")

    return admin.username


class PurgeTrashRequest(BaseModel):
    """Request body for trash purge."""

    older_than_days: int | None = None


class PurgeTrashResponse(BaseModel):
    """Response for trash purge."""

    files_deleted: int
    chunks_deleted: int
    older_than_days: int


@router.post("/purge-trash", response_model=PurgeTrashResponse)
async def purge_trash(
    request: Request,
    body: PurgeTrashRequest | None = None,
    _admin: str = Depends(require_admin_session),
) -> PurgeTrashResponse:
    """Purge old items from trash.

    Deletes files that have been in trash longer than the specified number of days.
    Also removes the associated chunk data from storage.

    Args:
        body: Optional request body with older_than_days override.

    Returns:
        Number of files and chunks deleted.
    """
    db = get_db(request)
    storage = get_storage(request)
    default_days = get_trash_retention_days(request)

    # Use request body value if provided, otherwise use default
    older_than_days = default_days
    if body and body.older_than_days is not None:
        older_than_days = body.older_than_days

    files_deleted, chunks_deleted = purge_trash_with_storage(db, storage, older_than_days)

    return PurgeTrashResponse(
        files_deleted=files_deleted,
        chunks_deleted=chunks_deleted,
        older_than_days=older_than_days,
    )
