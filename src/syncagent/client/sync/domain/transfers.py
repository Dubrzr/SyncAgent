"""Transfer state machine.

States:
    PENDING -> IN_PROGRESS -> COMPLETED
                           -> CANCELLED
                           -> FAILED

All state transitions are validated.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass


class TransferType(Enum):
    """Type of transfer operation."""

    UPLOAD = auto()
    DOWNLOAD = auto()
    DELETE = auto()


class TransferStatus(Enum):
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
    """A tracked transfer operation."""

    path: str
    transfer_type: TransferType
    status: TransferStatus = TransferStatus.PENDING

    # Version tracking (for conflict detection)
    base_version: int | None = None
    detected_server_version: int | None = None

    # Conflict info
    has_conflict: bool = False
    conflict_type: str | None = None

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

    def mark_conflict(self, conflict_type: str, server_version: int) -> None:
        """Flag potential conflict."""
        self.has_conflict = True
        self.conflict_type = conflict_type
        self.detected_server_version = server_version

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
