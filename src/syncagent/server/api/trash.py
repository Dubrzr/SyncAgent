"""Trash management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from syncagent.server.api.deps import get_current_token, get_db
from syncagent.server.database import Database
from syncagent.server.models import Token
from syncagent.server.schemas import FileResponse, file_to_response

router = APIRouter(prefix="/api/trash", tags=["trash"])


@router.get("", response_model=list[FileResponse])
def list_trash(
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> list[FileResponse]:
    """List deleted files."""
    files = db.list_trash()
    return [file_to_response(f) for f in files]


@router.post("/{path:path}/restore", response_model=FileResponse)
def restore_from_trash(
    path: str,
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> FileResponse:
    """Restore a file from trash."""
    db.restore_file_by_path(path)
    file = db.get_file(path)
    if file is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"File not found: {path}",
        )
    return file_to_response(file)
