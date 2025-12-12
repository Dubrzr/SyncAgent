"""Base worker class with cancellation support.

This module provides:
- WorkerState: Enum for worker lifecycle states
- WorkerResult: Result of a worker execution
- BaseWorker: Abstract base class for interruptible workers
"""

from __future__ import annotations

import logging
import threading
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncagent.client.sync.types import SyncEvent

logger = logging.getLogger(__name__)


class WorkerState(Enum):
    """State of a worker."""

    IDLE = auto()
    RUNNING = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


@dataclass
class WorkerResult:
    """Result of a worker execution.

    Attributes:
        success: Whether the operation succeeded.
        result: The result value if successful (type depends on worker).
        error: Error message if failed.
        cancelled: Whether the operation was cancelled.
        elapsed_time: Time taken in seconds.
    """

    success: bool
    result: Any = None
    error: str | None = None
    cancelled: bool = False
    elapsed_time: float = 0.0


@dataclass
class WorkerContext:
    """Context passed to worker execution.

    Attributes:
        event: The sync event being processed.
        cancel_check: Function to check if cancellation was requested.
        on_progress: Optional progress callback (current_bytes, total_bytes).
    """

    event: SyncEvent
    cancel_check: Callable[[], bool] = field(default=lambda: False)
    on_progress: Callable[[int, int], None] | None = None


class BaseWorker(ABC):
    """Abstract base class for interruptible workers.

    Workers process sync events (upload, download, delete) and support:
    - Cancellation at any point via cancel() method
    - Progress reporting via callbacks
    - Lifecycle hooks (on_complete, on_error, on_cancelled)

    Subclasses must implement:
    - _do_work(): The actual work logic
    - worker_type: Property returning the worker type name

    Usage:
        class MyWorker(BaseWorker):
            @property
            def worker_type(self) -> str:
                return "my_worker"

            def _do_work(self, ctx: WorkerContext) -> MyResult:
                # Do work, periodically check ctx.cancel_check()
                if ctx.cancel_check():
                    raise CancelledException()
                return MyResult(...)

        worker = MyWorker()
        result = worker.execute(event, on_progress=callback)
    """

    def __init__(self) -> None:
        """Initialize the worker."""
        self._worker_state = WorkerState.IDLE
        self._cancel_requested = False
        self._lock = threading.Lock()

        # Callbacks
        self._on_complete: Callable[[WorkerResult], None] | None = None
        self._on_error: Callable[[str], None] | None = None
        self._on_cancelled: Callable[[], None] | None = None

    @property
    @abstractmethod
    def worker_type(self) -> str:
        """Return the worker type name (e.g., 'upload', 'download')."""
        ...

    @property
    def state(self) -> WorkerState:
        """Get current worker state."""
        return self._worker_state

    @property
    def is_running(self) -> bool:
        """Check if worker is currently running."""
        return self._worker_state == WorkerState.RUNNING

    @property
    def cancel_requested(self) -> bool:
        """Check if cancellation was requested."""
        return self._cancel_requested

    def set_on_complete(self, callback: Callable[[WorkerResult], None]) -> None:
        """Set callback for successful completion."""
        self._on_complete = callback

    def set_on_error(self, callback: Callable[[str], None]) -> None:
        """Set callback for errors."""
        self._on_error = callback

    def set_on_cancelled(self, callback: Callable[[], None]) -> None:
        """Set callback for cancellation."""
        self._on_cancelled = callback

    def cancel(self) -> bool:
        """Request cancellation of the current operation.

        Returns:
            True if cancellation was requested, False if not running.
        """
        with self._lock:
            if self._worker_state != WorkerState.RUNNING:
                return False
            self._cancel_requested = True
            logger.info(f"{self.worker_type} worker: cancellation requested")
            return True

    def execute(
        self,
        event: SyncEvent,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        """Execute the worker operation.

        This is the main entry point that implements WorkerProtocol.

        Args:
            event: The sync event to process.
            on_progress: Optional callback (current_bytes, total_bytes).
            cancel_check: Optional external cancellation check function.

        Returns:
            True if successful, False otherwise.
        """
        with self._lock:
            if self._worker_state == WorkerState.RUNNING:
                logger.warning(f"{self.worker_type} worker: already running")
                return False
            self._worker_state = WorkerState.RUNNING
            self._cancel_requested = False

        start_time = time.time()

        # Combine internal and external cancel checks
        def combined_cancel_check() -> bool:
            if self._cancel_requested:
                return True
            if cancel_check and cancel_check():
                self._cancel_requested = True
                return True
            return False

        ctx = WorkerContext(
            event=event,
            cancel_check=combined_cancel_check,
            on_progress=on_progress,
        )

        try:
            result_value = self._do_work(ctx)
            elapsed = time.time() - start_time

            if self._cancel_requested:
                # Work completed but cancellation was requested
                self._worker_state = WorkerState.CANCELLED
                result = WorkerResult(
                    success=False,
                    cancelled=True,
                    elapsed_time=elapsed,
                )
                if self._on_cancelled:
                    self._on_cancelled()
                return False

            self._worker_state = WorkerState.COMPLETED
            result = WorkerResult(
                success=True,
                result=result_value,
                elapsed_time=elapsed,
            )
            if self._on_complete:
                self._on_complete(result)
            return True

        except CancelledException:
            elapsed = time.time() - start_time
            self._worker_state = WorkerState.CANCELLED
            logger.info(f"{self.worker_type} worker: cancelled after {elapsed:.2f}s")
            if self._on_cancelled:
                self._on_cancelled()
            return False

        except Exception as e:
            elapsed = time.time() - start_time
            self._worker_state = WorkerState.FAILED
            error_msg = str(e)
            logger.error(f"{self.worker_type} worker failed: {error_msg}")
            if self._on_error:
                self._on_error(error_msg)
            return False

        finally:
            with self._lock:
                if self._worker_state == WorkerState.RUNNING:
                    self._worker_state = WorkerState.IDLE

    @abstractmethod
    def _do_work(self, ctx: WorkerContext) -> Any:
        """Perform the actual work.

        Subclasses must implement this method. The implementation should:
        1. Periodically check ctx.cancel_check() and raise CancelledException if True
        2. Report progress via ctx.on_progress(current, total) if available
        3. Return the result on success

        Args:
            ctx: Worker context with event, cancel check, and progress callback.

        Returns:
            The result of the operation.

        Raises:
            CancelledException: If cancellation was requested.
            Exception: Any other error during execution.
        """
        ...

    def reset(self) -> None:
        """Reset worker to idle state for reuse."""
        with self._lock:
            if self._worker_state == WorkerState.RUNNING:
                raise RuntimeError("Cannot reset a running worker")
            self._worker_state = WorkerState.IDLE
            self._cancel_requested = False


class CancelledException(Exception):
    """Raised when a worker operation is cancelled."""

    pass
