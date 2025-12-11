"""Main API router that includes all sub-routers."""

from __future__ import annotations

from fastapi import APIRouter

from syncagent.server.api import chunks, files, health, machines, trash

router = APIRouter()

# Include all API routers
router.include_router(health.router)
router.include_router(machines.router)
router.include_router(files.router)
router.include_router(trash.router)
router.include_router(chunks.router)
