"""Machine management API routes."""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status

from syncagent.server.api.deps import get_current_token, get_db
from syncagent.server.database import SERVER_MACHINE_NAME, Database
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
    """Register a new machine using an invitation token."""
    # Validate invitation token
    invitation = db.validate_invitation(request.invitation_token)
    if not invitation:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired invitation token",
        )

    # Reject reserved machine name
    if request.name.lower() == SERVER_MACHINE_NAME:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Machine name '{SERVER_MACHINE_NAME}' is reserved",
        )

    # Create machine
    try:
        machine = db.create_machine(request.name, request.platform)
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Machine name '{request.name}' already exists",
        ) from e

    # Mark invitation as used
    db.use_invitation(request.invitation_token, machine.id)

    # Create auth token for machine
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
    """List all registered machines (excluding internal 'server' machine)."""
    machines = db.list_machines()
    # Filter out the internal server machine used for admin operations
    return [
        machine_to_response(m)
        for m in machines
        if m.name != SERVER_MACHINE_NAME
    ]


@router.delete("/{machine_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_machine(
    machine_id: int,
    db: Database = Depends(get_db),
    _auth: Token = Depends(get_current_token),
) -> Response:
    """Delete a machine and revoke its tokens."""
    # Prevent deletion of the internal server machine
    machine = db.get_machine(machine_id)
    if machine and machine.name == SERVER_MACHINE_NAME:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Cannot delete the internal server machine",
        )

    deleted = db.delete_machine(machine_id)
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Machine {machine_id} not found",
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
