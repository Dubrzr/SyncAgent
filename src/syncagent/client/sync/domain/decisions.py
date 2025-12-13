"""Decision matrix for concurrent events.

When a new event arrives while a transfer is in progress,
this module decides what action to take.

Matrix:
| New Event       | In Progress | Action                    |
|-----------------|-------------|---------------------------|
| LOCAL_MODIFIED  | DOWNLOAD    | Cancel download, upload   |
| LOCAL_DELETED   | DOWNLOAD    | Cancel download, delete   |
| REMOTE_MODIFIED | UPLOAD      | Mark conflict, continue   |
| REMOTE_DELETED  | UPLOAD      | Conflict-copy, continue   |
| *               | same type   | Ignore (already handling) |
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from syncagent.client.sync.domain.transfers import Transfer
    from syncagent.client.sync.types import SyncEvent


class DecisionAction(Enum):
    """Action to take on concurrent event."""

    IGNORE = auto()  # Already handling this path
    CANCEL_AND_REQUEUE = auto()  # Cancel current, queue new
    MARK_CONFLICT = auto()  # Continue but flag potential conflict
    CREATE_CONFLICT_COPY = auto()  # Save local before overwrite


@dataclass(frozen=True)
class DecisionRule:
    """A rule in the decision matrix."""

    new_event_source: str  # "LOCAL" or "REMOTE"
    new_event_type: str | None  # Specific type or None for any
    existing_transfer: str  # "UPLOAD", "DOWNLOAD", or "DELETE"
    action: DecisionAction
    reason: str


# Declarative decision rules
DECISION_RULES: list[DecisionRule] = [
    # Local events during download -> cancel download, handle local
    DecisionRule(
        new_event_source="LOCAL",
        new_event_type=None,  # Any local event
        existing_transfer="DOWNLOAD",
        action=DecisionAction.CANCEL_AND_REQUEUE,
        reason="Local change takes precedence over incoming remote",
    ),
    # Remote modified during upload -> potential conflict
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type="REMOTE_MODIFIED",
        existing_transfer="UPLOAD",
        action=DecisionAction.MARK_CONFLICT,
        reason="Server changed while uploading, may conflict at commit",
    ),
    # Remote deleted during upload -> create conflict copy
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type="REMOTE_DELETED",
        existing_transfer="UPLOAD",
        action=DecisionAction.CREATE_CONFLICT_COPY,
        reason="Server deleted, but user has local changes to preserve",
    ),
    # Remote events during download -> ignore
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type=None,
        existing_transfer="DOWNLOAD",
        action=DecisionAction.IGNORE,
        reason="Already downloading latest from server",
    ),
    # Local events during upload -> ignore
    DecisionRule(
        new_event_source="LOCAL",
        new_event_type=None,
        existing_transfer="UPLOAD",
        action=DecisionAction.IGNORE,
        reason="Already uploading local changes",
    ),
]


class DecisionMatrix:
    """Evaluates decision rules for concurrent events."""

    def __init__(self, rules: list[DecisionRule] | None = None) -> None:
        self._rules = rules or DECISION_RULES

    def evaluate(
        self,
        new_event_source: str,
        new_event_type: str,
        existing_transfer_type: str,
    ) -> tuple[DecisionAction, str]:
        """Evaluate rules and return action with reason.

        Args:
            new_event_source: "LOCAL" or "REMOTE"
            new_event_type: Event type name (e.g., "LOCAL_MODIFIED")
            existing_transfer_type: "UPLOAD", "DOWNLOAD", or "DELETE"

        Returns:
            (action, reason) tuple
        """
        for rule in self._rules:
            if self._matches(
                rule, new_event_source, new_event_type, existing_transfer_type
            ):
                return rule.action, rule.reason

        # Default: ignore unknown combinations
        return DecisionAction.IGNORE, "No matching rule, ignoring"

    def _matches(
        self,
        rule: DecisionRule,
        source: str,
        event_type: str,
        transfer_type: str,
    ) -> bool:
        return (
            rule.new_event_source == source
            and rule.existing_transfer == transfer_type
            and (rule.new_event_type is None or rule.new_event_type == event_type)
        )


def decide(new_event: SyncEvent, existing_transfer: Transfer) -> DecisionAction:
    """Quick decision lookup.

    Args:
        new_event: The new event that arrived
        existing_transfer: The transfer currently in progress

    Returns:
        The action to take
    """
    matrix = DecisionMatrix()
    action, _ = matrix.evaluate(
        new_event_source=new_event.source.name,
        new_event_type=new_event.event_type.name,
        existing_transfer_type=existing_transfer.transfer_type.name,
    )
    return action
