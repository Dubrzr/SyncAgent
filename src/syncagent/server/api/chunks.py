"""Chunk storage API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status

from syncagent.server.api.deps import get_current_token, get_storage
from syncagent.server.models import Token
from syncagent.server.storage import ChunkNotFoundError, ChunkStorage

router = APIRouter(prefix="/api/storage/chunks", tags=["storage"])


@router.put("/{chunk_hash}")
async def upload_chunk(
    chunk_hash: str,
    request: Request,
    storage: ChunkStorage = Depends(get_storage),
    _auth: Token = Depends(get_current_token),
) -> Response:
    """Upload an encrypted chunk."""
    data = await request.body()
    if not data:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Empty chunk data",
        )
    storage.put(chunk_hash, data)
    return Response(status_code=status.HTTP_201_CREATED)


@router.get("/{chunk_hash}")
def download_chunk(
    chunk_hash: str,
    storage: ChunkStorage = Depends(get_storage),
    _auth: Token = Depends(get_current_token),
) -> Response:
    """Download an encrypted chunk."""
    try:
        data = storage.get(chunk_hash)
    except ChunkNotFoundError as e:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk not found: {chunk_hash}",
        ) from e
    return Response(content=data, media_type="application/octet-stream")


@router.head("/{chunk_hash}")
def check_chunk_exists(
    chunk_hash: str,
    storage: ChunkStorage = Depends(get_storage),
    _auth: Token = Depends(get_current_token),
) -> Response:
    """Check if a chunk exists."""
    if storage.exists(chunk_hash):
        return Response(status_code=status.HTTP_200_OK)
    return Response(status_code=status.HTTP_404_NOT_FOUND)


@router.delete("/{chunk_hash}")
def delete_chunk(
    chunk_hash: str,
    storage: ChunkStorage = Depends(get_storage),
    _auth: Token = Depends(get_current_token),
) -> Response:
    """Delete a chunk from storage."""
    deleted = storage.delete(chunk_hash)
    if deleted:
        return Response(status_code=status.HTTP_204_NO_CONTENT)
    raise HTTPException(
        status_code=status.HTTP_404_NOT_FOUND,
        detail=f"Chunk not found: {chunk_hash}",
    )
