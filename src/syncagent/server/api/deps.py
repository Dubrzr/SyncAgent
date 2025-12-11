"""FastAPI dependencies for API routes."""

from __future__ import annotations

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from syncagent.server.database import Database
from syncagent.server.models import Token
from syncagent.server.storage import ChunkStorage

# Security scheme
security = HTTPBearer(auto_error=False)


def get_db(request: Request) -> Database:
    """Get database from app state."""
    db: Database = request.app.state.db
    return db


def get_storage(request: Request) -> ChunkStorage:
    """Get chunk storage from app state."""
    storage: ChunkStorage | None = request.app.state.storage
    if storage is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Chunk storage not configured",
        )
    return storage


def get_current_token(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security),
) -> Token:
    """Validate bearer token and return Token object."""
    db = get_db(request)
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    token = db.validate_token(credentials.credentials)
    if token is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    # Update last_seen for the machine
    db.update_machine_last_seen(token.machine_id)
    return token
