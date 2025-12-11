"""Health check API route."""

from __future__ import annotations

from fastapi import APIRouter

from syncagent.server.schemas import HealthResponse

router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    """Check server health."""
    return HealthResponse(status="ok")
