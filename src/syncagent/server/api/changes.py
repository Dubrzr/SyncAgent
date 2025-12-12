"""Change log API route for incremental sync.

This endpoint allows clients to poll for changes since their last sync,
instead of fetching all files every time (Phase 14.2).
"""

from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query

from syncagent.server.api.deps import get_current_token, get_db
from syncagent.server.database import Database
from syncagent.server.models import Token
from syncagent.server.schemas import ChangesResponse, change_to_response

router = APIRouter(prefix="/changes", tags=["changes"])


@router.get("", response_model=ChangesResponse)
def get_changes(
    since: str = Query(
        ...,
        description="ISO 8601 timestamp. Get changes after this time.",
        example="2024-01-01T00:00:00Z",
    ),
    limit: int = Query(
        default=1000,
        ge=1,
        le=10000,
        description="Maximum number of changes to return.",
    ),
    db: Database = Depends(get_db),
    _token: Token = Depends(get_current_token),
) -> ChangesResponse:
    """Get changes since a given timestamp.

    This endpoint is used for incremental sync. Clients should:
    1. On first sync, use a very old timestamp (e.g., 1970-01-01)
    2. Store the latest_timestamp from the response
    3. On subsequent syncs, use the stored timestamp as 'since'

    Returns:
        ChangesResponse with list of changes and metadata.
    """
    # Parse the timestamp
    since_dt = datetime.fromisoformat(since.replace("Z", "+00:00"))

    # Get changes from database
    changes = db.get_changes_since(since_dt, limit=limit + 1)

    # Check if there are more changes
    has_more = len(changes) > limit
    if has_more:
        changes = changes[:limit]

    # Get latest timestamp from changes
    latest_timestamp = None
    if changes:
        latest_timestamp = changes[-1].timestamp.isoformat()

    return ChangesResponse(
        changes=[change_to_response(c) for c in changes],
        has_more=has_more,
        latest_timestamp=latest_timestamp,
    )


@router.get("/latest")
def get_latest_timestamp(
    db: Database = Depends(get_db),
    _token: Token = Depends(get_current_token),
) -> dict[str, str | None]:
    """Get the timestamp of the most recent change.

    This can be used by clients to quickly check if there are any changes
    without fetching all the details.

    Returns:
        Dict with latest_timestamp (or null if no changes).
    """
    latest = db.get_latest_change_timestamp()
    return {
        "latest_timestamp": latest.isoformat() if latest else None,
    }
