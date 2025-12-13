"""Domain modules for sync business rules.

This package centralizes business logic for the sync system:
- priorities: mtime-aware event deduplication
- transfers: Transfer state machine and types
- conflicts: Conflict outcome types
- decisions: Decision matrix for concurrent events

Architecture:
    domain/ contains pure business logic without external dependencies.
    Implementation details (state updates, API calls) stay in workers/.
"""

from syncagent.client.sync.domain.conflicts import (
    ConflictOutcome,
    RaceConditionError,
)
from syncagent.client.sync.domain.decisions import (
    DecisionAction,
    DecisionMatrix,
    DecisionRule,
    decide,
)
from syncagent.client.sync.domain.priorities import (
    EventComparator,
    MtimeAwareComparator,
)
from syncagent.client.sync.domain.transfers import (
    InvalidTransitionError,
    Transfer,
    TransferStatus,
    TransferTracker,
    TransferType,
)

__all__ = [
    # priorities
    "EventComparator",
    "MtimeAwareComparator",
    # transfers
    "TransferType",
    "TransferStatus",
    "Transfer",
    "TransferTracker",
    "InvalidTransitionError",
    # conflicts
    "ConflictOutcome",
    "RaceConditionError",
    # decisions
    "DecisionAction",
    "DecisionRule",
    "DecisionMatrix",
    "decide",
]
