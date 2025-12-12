"""Pydantic schemas for API request/response models."""

from __future__ import annotations

from pydantic import BaseModel

from syncagent.server.models import ChangeLog, FileMetadata, Machine

# === Machine schemas ===


class MachineRegisterRequest(BaseModel):
    """Request body for machine registration."""

    name: str
    platform: str
    invitation_token: str


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


# === Change log schemas ===


class ChangeResponse(BaseModel):
    """Single change entry in response."""

    id: int
    file_path: str
    action: str  # CREATED, UPDATED, DELETED
    version: int
    machine_id: int
    timestamp: str


class ChangesResponse(BaseModel):
    """Response for /api/changes endpoint."""

    changes: list[ChangeResponse]
    has_more: bool  # True if there are more changes (limit was hit)
    latest_timestamp: str | None  # Timestamp of last change in response


def change_to_response(change: ChangeLog) -> ChangeResponse:
    """Convert ChangeLog to response model."""
    return ChangeResponse(
        id=change.id,
        file_path=change.file_path,
        action=change.action,
        version=change.version,
        machine_id=change.machine_id,
        timestamp=change.timestamp.isoformat(),
    )
