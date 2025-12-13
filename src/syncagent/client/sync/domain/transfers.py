"""Transfer state machine.

States:
    PENDING -> IN_PROGRESS -> COMPLETED
                           -> CANCELLED
                           -> FAILED

All state transitions are validated.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import IntEnum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from syncagent.client.sync.types import SyncEvent


class TransferType(IntEnum):
    """Type of transfer operation."""

    UPLOAD = auto()
    DOWNLOAD = auto()
    DELETE = auto()


class TransferStatus(IntEnum):
    """Status of a transfer."""

    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


# Valid state transitions
VALID_TRANSITIONS: dict[TransferStatus, set[TransferStatus]] = {
    TransferStatus.PENDING: {TransferStatus.IN_PROGRESS, TransferStatus.CANCELLED},
    TransferStatus.IN_PROGRESS: {
        TransferStatus.COMPLETED,
        TransferStatus.CANCELLED,
        TransferStatus.FAILED,
    },
    TransferStatus.COMPLETED: set(),  # Terminal
    TransferStatus.CANCELLED: set(),  # Terminal
    TransferStatus.FAILED: set(),  # Terminal
}


class InvalidTransitionError(Exception):
    """Raised when attempting invalid state transition."""

    pass


@dataclass
class Transfer:
    """A tracked transfer operation.

    Attributes:
        path: Relative file path
        transfer_type: Type of operation (upload/download/delete)
        status: Current status
        event: The event that triggered this transfer
        started_at: When the transfer started
        cancel_requested: Flag to request cancellation (checked by workers)
        error: Error message if failed
        base_version: Server version this transfer is based on (for uploads)
        detected_server_version: Latest server version detected during transfer
        has_conflict: Whether a conflict was detected
        conflict_type: Type of conflict if detected
    """

    path: str
    transfer_type: TransferType
    status: TransferStatus = TransferStatus.PENDING

    # Event that triggered this transfer
    event: SyncEvent | None = None
    started_at: float = field(default_factory=time.time)

    # Cancellation flag (workers check this)
    cancel_requested: bool = False
    error: str | None = None

    # Version tracking (for conflict detection)
    base_version: int | None = None
    detected_server_version: int | None = None

    # Conflict info
    has_conflict: bool = False
    conflict_type: Any = None  # Can be ConflictType enum or string

    # Callbacks
    _on_complete: Callable[[Transfer], None] | None = field(default=None, repr=False)
    _on_error: Callable[[Transfer, Exception], None] | None = field(
        default=None, repr=False
    )

    def transition_to(self, new_status: TransferStatus) -> None:
        """Transition to a new status with validation."""
        if new_status not in VALID_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"Cannot transition from {self.status.name} to {new_status.name}"
            )
        self.status = new_status

    def start(self) -> None:
        """Mark transfer as started."""
        self.transition_to(TransferStatus.IN_PROGRESS)

    def complete(self) -> None:
        """Mark transfer as completed."""
        self.transition_to(TransferStatus.COMPLETED)
        if self._on_complete:
            self._on_complete(self)

    def cancel(self) -> None:
        """Mark transfer as cancelled."""
        if self.status in (TransferStatus.PENDING, TransferStatus.IN_PROGRESS):
            self.transition_to(TransferStatus.CANCELLED)

    def fail(self, error: Exception) -> None:
        """Mark transfer as failed."""
        self.transition_to(TransferStatus.FAILED)
        if self._on_error:
            self._on_error(self, error)

    def request_cancel(self) -> None:
        """Request cancellation of this transfer.

        Sets the cancel_requested flag for workers to check.
        Does not change status - that happens when worker acknowledges.
        """
        self.cancel_requested = True

    def set_conflict(
        self,
        conflict_type: Any,  # Can be ConflictType enum or string
        detected_version: int | None = None,
    ) -> None:
        """Mark this transfer as having a conflict.

        Args:
            conflict_type: When/how the conflict was detected
            detected_version: The server version that caused the conflict
        """
        self.has_conflict = True
        self.conflict_type = conflict_type  # Keep original type (enum or string)
        if detected_version is not None:
            self.detected_server_version = detected_version
        self.request_cancel()  # Auto-cancel on conflict

    def mark_conflict(self, conflict_type: Any, server_version: int | None) -> None:
        """Flag potential conflict (alias for set_conflict)."""
        self.set_conflict(conflict_type, server_version)

    @property
    def is_terminal(self) -> bool:
        """Check if transfer is in a terminal state."""
        return self.status in (
            TransferStatus.COMPLETED,
            TransferStatus.CANCELLED,
            TransferStatus.FAILED,
        )


class TransferTracker:
    """Tracks active transfers by path."""

    def __init__(self) -> None:
        self._transfers: dict[str, Transfer] = {}

    def create(
        self,
        path: str,
        transfer_type: TransferType,
        base_version: int | None = None,
        on_complete: Callable[[Transfer], None] | None = None,
        on_error: Callable[[Transfer, Exception], None] | None = None,
    ) -> Transfer:
        """Create and track a new transfer."""
        transfer = Transfer(
            path=path,
            transfer_type=transfer_type,
            base_version=base_version,
            _on_complete=on_complete,
            _on_error=on_error,
        )
        self._transfers[path] = transfer
        return transfer

    def get(self, path: str) -> Transfer | None:
        """Get transfer for path."""
        return self._transfers.get(path)

    def get_active(self, path: str) -> Transfer | None:
        """Get transfer only if not terminal."""
        transfer = self._transfers.get(path)
        if transfer and not transfer.is_terminal:
            return transfer
        return None

    def remove(self, path: str) -> None:
        """Remove transfer from tracking."""
        self._transfers.pop(path, None)

    def all_active(self) -> list[Transfer]:
        """Get all non-terminal transfers."""
        return [t for t in self._transfers.values() if not t.is_terminal]

    def cancel_all(self) -> None:
        """Cancel all active transfers."""
        for transfer in self.all_active():
            transfer.cancel()

    def __len__(self) -> int:
        """Get total number of tracked transfers."""
        return len(self._transfers)

    def __contains__(self, path: str) -> bool:
        """Check if path is being tracked."""
        return path in self._transfers
