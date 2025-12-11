"""Machine management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from syncagent.server.api.deps import get_current_token, get_db
from syncagent.server.database import Database
from syncagent.server.models import Token
from syncagent.server.schemas import (
    MachineRegisterRequest,
    MachineRegisterResponse,
    MachineResponse,
    machine_to_response,
)

router = APIRouter(prefix="/api/machines", tags=["machines"])


@router.post(
    "/register",
    response_model=MachineRegisterResponse,
    status_code=status.HTTP_201_CREATED,
)
def register_machine(
    request: MachineRegisterRequest,
    db: Database = Depends(get_db),
) -> MachineRegisterResponse:
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


@router.get("", response_model=list[MachineResponse])
def list_machines(
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> list[MachineResponse]:
    """List all registered machines."""
    machines = db.list_machines()
    return [machine_to_response(m) for m in machines]
