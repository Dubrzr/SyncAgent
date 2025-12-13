"""File management API routes."""

from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.exc import IntegrityError

from syncagent.server.api.deps import get_current_token, get_db
from syncagent.server.database import ConflictError, Database
from syncagent.server.models import Token
from syncagent.server.schemas import (
    FileCreateRequest,
    FileResponse,
    FileUpdateRequest,
    file_to_response,
)
from syncagent.server.ws import get_hub

router = APIRouter(prefix="/api", tags=["files"])


@router.get("/files", response_model=list[FileResponse])
def list_files(
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
    prefix: str | None = None,
) -> list[FileResponse]:
    """List all files (excluding deleted)."""
    files = db.list_files(prefix=prefix)
    return [file_to_response(f) for f in files]


@router.post(
    "/files",
    response_model=FileResponse,
    status_code=status.HTTP_201_CREATED,
)
def create_file(
    request: FileCreateRequest,
    db: Database = Depends(get_db),
    auth: Token = Depends(get_current_token),
) -> FileResponse:
    """Create file metadata."""
    try:
        file = db.create_file(
            path=request.path,
            size=request.size,
            content_hash=request.content_hash,
            machine_id=auth.machine_id,
        )
    except IntegrityError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"File already exists: {request.path}",
        ) from e
    if request.chunks:
        db.set_file_chunks(request.path, request.chunks)
    return file_to_response(file)


# Note: chunks endpoint must be before generic {path:path} routes
@router.get("/chunks/{path:path}", response_model=list[str])
def get_file_chunks(
    path: str,
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> list[str]:
    """Get chunks for a file."""
    file = db.get_file(path)
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )
    return db.get_file_chunks(path)


@router.get("/files/{path:path}", response_model=FileResponse)
def get_file(
    path: str,
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> FileResponse:
    """Get file metadata by path."""
    file = db.get_file(path)
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )
    return file_to_response(file)


@router.put("/files/{path:path}", response_model=FileResponse)
def update_file(
    path: str,
    request: FileUpdateRequest,
    db: Database = Depends(get_db),
    auth: Token = Depends(get_current_token),
) -> FileResponse:
    """Update file metadata with conflict detection."""
    try:
        file = db.update_file(
            path=path,
            size=request.size,
            content_hash=request.content_hash,
            machine_id=auth.machine_id,
            parent_version=request.parent_version,
        )
    except ConflictError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e),
        ) from e
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(e),
        ) from e

    if request.chunks:
        db.set_file_chunks(path, request.chunks)
    return file_to_response(file)


@router.delete("/files/{path:path}")
async def delete_file(
    path: str,
    db: Database = Depends(get_db),
    auth: Token = Depends(get_current_token),
) -> Response:
    """Soft-delete a file or folder (move to trash).

    If path is an exact file, deletes that file.
    If path is a folder prefix, deletes all files under that folder.
    Notifies connected clients via WebSocket push.
    """
    # Get files that will be deleted (for notification)
    # Check exact file first
    file = db.get_file(path)
    paths_to_notify: list[str] = []

    if file:
        paths_to_notify = [path]
    else:
        # Try as folder prefix
        folder_path = path if path.endswith("/") else path + "/"
        files = db.list_files(prefix=folder_path)
        paths_to_notify = [f.path for f in files]

    # Perform the deletion
    db.delete_file(path, auth.machine_id)

    # Notify connected clients (exclude the machine that initiated the delete)
    if paths_to_notify:
        hub = get_hub()
        timestamp = datetime.now(UTC).isoformat()
        for file_path in paths_to_notify:
            await hub.notify_file_change(
                action="DELETED",
                file_path=file_path,
                timestamp=timestamp,
                exclude_machine_id=auth.machine_id,
            )

    return Response(status_code=status.HTTP_204_NO_CONTENT)
