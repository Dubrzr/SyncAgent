"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from pydantic import BaseModel

from syncagent.server.models import FileMetadata, Machine

# === Machine schemas ===


class MachineRegisterRequest(BaseModel):
    """Request body for machine registration."""

    name: str
    platform: str


class MachineResponse(BaseModel):
    """Machine data in responses."""

    id: int
    name: str
    platform: str
    created_at: str
    last_seen: str


class MachineRegisterResponse(BaseModel):
    """Response for machine registration."""

    token: str
    machine: MachineResponse


# === File schemas ===


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


# === Health schema ===


class HealthResponse(BaseModel):
    """Health check response."""

    status: str


# === Converters ===


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
