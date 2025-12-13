"""Domain modules for sync business rules.

This package centralizes all business logic for the sync system:
- priorities: Event priority and ordering logic
- transfers: Transfer state machine
- versions: Version tracking and comparison
- conflicts: Conflict detection and resolution
- decisions: Decision matrix for concurrent events
"""

from syncagent.client.sync.domain.conflicts import (
    ConflictContext,
    ConflictOutcome,
    ConflictResolution,
    ConflictType,
    PreDownloadConflictDetector,
    PreUploadConflictDetector,
    RaceConditionError,
    generate_conflict_filename,
    safe_rename,
)
from syncagent.client.sync.domain.decisions import (
    DecisionAction,
    DecisionMatrix,
    DecisionRule,
    decide,
)
from syncagent.client.sync.domain.priorities import (
    MtimeAwareComparator,
    Priority,
    PriorityRule,
    get_priority,
    get_priority_reason,
)
from syncagent.client.sync.domain.transfers import (
    InvalidTransitionError,
    Transfer,
    TransferStatus,
    TransferTracker,
    TransferType,
)
from syncagent.client.sync.domain.versions import (
    VersionChecker,
    VersionInfo,
    VersionUpdater,
)

__all__ = [
    # priorities
    "Priority",
    "PriorityRule",
    "MtimeAwareComparator",
    "get_priority",
    "get_priority_reason",
    # transfers
    "TransferType",
    "TransferStatus",
    "Transfer",
    "TransferTracker",
    "InvalidTransitionError",
    # versions
    "VersionInfo",
    "VersionChecker",
    "VersionUpdater",
    # conflicts
    "ConflictType",
    "ConflictOutcome",
    "ConflictContext",
    "ConflictResolution",
    "PreDownloadConflictDetector",
    "PreUploadConflictDetector",
    "RaceConditionError",
    "generate_conflict_filename",
    "safe_rename",
    # decisions
    "DecisionAction",
    "DecisionRule",
    "DecisionMatrix",
    "decide",
]
