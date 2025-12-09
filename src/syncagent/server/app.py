"""FastAPI application for SyncAgent server.

This module provides the REST API for:
- Machine registration and management
- File metadata operations
- Chunk management
- Trash operations
"""

from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel

from syncagent.server.database import ConflictError, Database
from syncagent.server.models import FileMetadata, Machine, Token
from syncagent.server.storage import ChunkNotFoundError, ChunkStorage

# Global security scheme
_security = HTTPBearer(auto_error=False)


# === Pydantic models for request/response ===


class MachineRegisterRequest(BaseModel):
    """Request body for machine registration."""

    name: str
    platform: str


class MachineRegisterResponse(BaseModel):
    """Response for machine registration."""

    token: str
    machine: MachineResponse


class MachineResponse(BaseModel):
    """Machine data in responses."""

    id: int
    name: str
    platform: str
    created_at: str
    last_seen: str


class FileCreateRequest(BaseModel):
    """Request body for file creation."""

    path: str
    size: int
    content_hash: str
    chunks: list[str]


class FileUpdateRequest(BaseModel):
    """Request body for file update."""

    size: int
    content_hash: str
    parent_version: int
    chunks: list[str]


class FileResponse(BaseModel):
    """File metadata in responses."""

    id: int
    path: str
    size: int
    content_hash: str
    version: int
    created_at: str
    updated_at: str
    deleted_at: str | None


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


# === Helper functions ===


def machine_to_response(machine: Machine) -> MachineResponse:
    """Convert Machine to response model."""
    return MachineResponse(
        id=machine.id,
        name=machine.name,
        platform=machine.platform,
        created_at=machine.created_at.isoformat(),
        last_seen=machine.last_seen.isoformat(),
    )


def file_to_response(file: FileMetadata) -> FileResponse:
    """Convert FileMetadata to response model."""
    return FileResponse(
        id=file.id,
        path=file.path,
        size=file.size,
        content_hash=file.content_hash,
        version=file.version,
        created_at=file.created_at.isoformat(),
        updated_at=file.updated_at.isoformat(),
        deleted_at=file.deleted_at.isoformat() if file.deleted_at else None,
    )


# === Application factory ===


def create_app(db: Database, storage: ChunkStorage | None = None) -> FastAPI:
    """Create FastAPI application with database and storage.

    Args:
        db: Database instance.
        storage: Optional ChunkStorage instance for blob storage.

    Returns:
        Configured FastAPI application.
    """
    app = FastAPI(
        title="SyncAgent Server",
        description="Zero-Knowledge E2EE File Sync Server",
        version="0.1.0",
    )

    # Store database and storage in app state for access in dependencies
    app.state.db = db
    app.state.storage = storage

    def get_db(request: Request) -> Database:
        """Get database from request state."""
        database: Database = request.app.state.db
        return database

    def get_storage(request: Request) -> ChunkStorage:
        """Get storage from request state."""
        chunk_storage: ChunkStorage | None = request.app.state.storage
        if chunk_storage is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Chunk storage not configured",
            )
        return chunk_storage

    def get_current_token(
        request: Request,
        credentials: HTTPAuthorizationCredentials | None = Depends(_security),
    ) -> Token:
        """Validate bearer token and return Token object."""
        database = get_db(request)
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing authentication credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        token = database.validate_token(credentials.credentials)
        if token is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )
        # Update last_seen for the machine
        database.update_machine_last_seen(token.machine_id)
        return token

    # === Health endpoint ===

    @app.get("/health", response_model=HealthResponse)
    def health_check() -> HealthResponse:
        """Check server health."""
        return HealthResponse(status="ok")

    # === Machine endpoints ===

    @app.post(
        "/api/machines/register",
        response_model=MachineRegisterResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def register_machine(request: MachineRegisterRequest) -> MachineRegisterResponse:
        """Register a new machine and get authentication token."""
        try:
            machine = db.create_machine(request.name, request.platform)
        except Exception as e:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Machine name '{request.name}' already exists",
            ) from e

        raw_token, _ = db.create_token(machine.id)
        return MachineRegisterResponse(
            token=raw_token,
            machine=machine_to_response(machine),
        )

    @app.get("/api/machines", response_model=list[MachineResponse])
    def list_machines(_auth: Token = Depends(get_current_token)) -> list[MachineResponse]:
        """List all registered machines."""
        machines = db.list_machines()
        return [machine_to_response(m) for m in machines]

    # === File endpoints ===

    @app.get("/api/files", response_model=list[FileResponse])
    def list_files(
        _auth: Token = Depends(get_current_token),
        prefix: str | None = None,
    ) -> list[FileResponse]:
        """List all files (excluding deleted)."""
        files = db.list_files(prefix=prefix)
        return [file_to_response(f) for f in files]

    @app.post(
        "/api/files",
        response_model=FileResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_file(
        request: FileCreateRequest,
        auth: Token = Depends(get_current_token),
    ) -> FileResponse:
        """Create file metadata."""
        file = db.create_file(
            path=request.path,
            size=request.size,
            content_hash=request.content_hash,
            machine_id=auth.machine_id,
        )
        if request.chunks:
            db.set_file_chunks(request.path, request.chunks)
        return file_to_response(file)

    # Note: chunks endpoint must be before generic {path:path} routes
    @app.get("/api/chunks/{path:path}", response_model=list[str])
    def get_file_chunks(
        path: str,
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

    @app.get("/api/files/{path:path}", response_model=FileResponse)
    def get_file(
        path: str,
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

    @app.put("/api/files/{path:path}", response_model=FileResponse)
    def update_file(
        path: str,
        request: FileUpdateRequest,
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

    @app.delete("/api/files/{path:path}")
    def delete_file(
        path: str,
        auth: Token = Depends(get_current_token),
    ) -> Response:
        """Soft-delete a file (move to trash)."""
        db.delete_file(path, auth.machine_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    # === Trash endpoints ===

    @app.get("/api/trash", response_model=list[FileResponse])
    def list_trash(_auth: Token = Depends(get_current_token)) -> list[FileResponse]:
        """List deleted files."""
        files = db.list_trash()
        return [file_to_response(f) for f in files]

    @app.post("/api/trash/{path:path}/restore", response_model=FileResponse)
    def restore_from_trash(
        path: str,
        _auth: Token = Depends(get_current_token),
    ) -> FileResponse:
        """Restore a file from trash."""
        db.restore_file(path)
        file = db.get_file(path)
        if file is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"File not found: {path}",
            )
        return file_to_response(file)

    # === Chunk storage endpoints ===

    @app.put("/api/storage/chunks/{chunk_hash}")
    async def upload_chunk(
        chunk_hash: str,
        request: Request,
        _auth: Token = Depends(get_current_token),
        chunk_storage: ChunkStorage = Depends(get_storage),
    ) -> Response:
        """Upload an encrypted chunk."""
        data = await request.body()
        if not data:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Empty chunk data",
            )
        chunk_storage.put(chunk_hash, data)
        return Response(status_code=status.HTTP_201_CREATED)

    @app.get("/api/storage/chunks/{chunk_hash}")
    def download_chunk(
        chunk_hash: str,
        _auth: Token = Depends(get_current_token),
        chunk_storage: ChunkStorage = Depends(get_storage),
    ) -> Response:
        """Download an encrypted chunk."""
        try:
            data = chunk_storage.get(chunk_hash)
        except ChunkNotFoundError as e:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Chunk not found: {chunk_hash}",
            ) from e
        return Response(content=data, media_type="application/octet-stream")

    @app.head("/api/storage/chunks/{chunk_hash}")
    def check_chunk_exists(
        chunk_hash: str,
        _auth: Token = Depends(get_current_token),
        chunk_storage: ChunkStorage = Depends(get_storage),
    ) -> Response:
        """Check if a chunk exists."""
        if chunk_storage.exists(chunk_hash):
            return Response(status_code=status.HTTP_200_OK)
        return Response(status_code=status.HTTP_404_NOT_FOUND)

    @app.delete("/api/storage/chunks/{chunk_hash}")
    def delete_chunk(
        chunk_hash: str,
        _auth: Token = Depends(get_current_token),
        chunk_storage: ChunkStorage = Depends(get_storage),
    ) -> Response:
        """Delete a chunk from storage."""
        deleted = chunk_storage.delete(chunk_hash)
        if deleted:
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Chunk not found: {chunk_hash}",
        )

    return app
