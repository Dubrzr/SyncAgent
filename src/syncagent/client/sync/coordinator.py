"""Sync coordinator for orchestrating file synchronization.

This module provides:
- SyncCoordinator: Central orchestrator that processes events and dispatches work
- Decision matrix for handling concurrent events

The coordinator is the "brain" of the sync system:
1. Consumes events from the EventQueue
2. Applies decision rules based on current state
3. Dispatches work to upload/download workers
4. Handles cancellation of in-progress transfers when needed

Decision Matrix:
    | Event           | In Progress      | Action                              |
    |-----------------|------------------|-------------------------------------|
    | LOCAL_MODIFIED  | DOWNLOAD same    | Cancel download, queue upload       |
    | REMOTE_MODIFIED | UPLOAD same      | Mark potential conflict             |
    | LOCAL_DELETED   | DOWNLOAD same    | Cancel download, propagate delete   |
    | REMOTE_DELETED  | UPLOAD same      | Create conflict-copy, continue      |
    | LOCAL_MODIFIED  | None             | Queue upload                        |
    | REMOTE_MODIFIED | None             | Queue download                      |
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Protocol

from syncagent.client.sync.types import (
    CoordinatorState,
    CoordinatorStats,
    SyncEvent,
    SyncEventSource,
    SyncEventType,
    TransferState,
    TransferStatus,
    TransferType,
)

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncagent.client.sync.queue import EventQueue

logger = logging.getLogger(__name__)


class WorkerProtocol(Protocol):
    """Protocol for transfer workers.

    Workers must implement this interface to be used by the coordinator.
    """

    def execute(
        self,
        event: SyncEvent,
        on_progress: Callable[[int, int], None] | None = None,
        cancel_check: Callable[[], bool] | None = None,
    ) -> bool:
        """Execute the transfer operation.

        Args:
            event: The sync event to process
            on_progress: Optional callback (current, total) for progress
            cancel_check: Optional function that returns True if cancelled

        Returns:
            True if successful, False otherwise
        """
        ...


class SyncCoordinator:
    """Central orchestrator for sync operations.

    The coordinator runs in its own thread, consuming events from the queue
    and dispatching work to workers.

    Usage:
        queue = EventQueue()
        coordinator = SyncCoordinator(queue)

        # Register workers
        coordinator.register_worker(TransferType.UPLOAD, upload_worker)
        coordinator.register_worker(TransferType.DOWNLOAD, download_worker)

        # Start processing
        coordinator.start()

        # ... events are processed automatically ...

        # Stop when done
        coordinator.stop()
    """

    def __init__(
        self,
        queue: EventQueue,
        max_concurrent: int = 4,
    ) -> None:
        """Initialize the coordinator.

        Args:
            queue: Event queue to consume from
            max_concurrent: Maximum concurrent transfers (not yet implemented)
        """
        self._queue = queue
        self._max_concurrent = max_concurrent

        # State
        self._state = CoordinatorState.STOPPED
        self._lock = threading.RLock()
        self._stop_event = threading.Event()

        # Transfer tracking: path -> TransferState
        self._transfers: dict[str, TransferState] = {}

        # Workers: TransferType -> worker
        self._workers: dict[TransferType, WorkerProtocol] = {}

        # Processing thread
        self._thread: threading.Thread | None = None

        # Stats
        self._stats = CoordinatorStats()

        # Callbacks
        self._on_transfer_complete: Callable[[TransferState], None] | None = None
        self._on_conflict: Callable[[str, SyncEvent, SyncEvent], None] | None = None

    @property
    def state(self) -> CoordinatorState:
        """Get current coordinator state."""
        return self._state

    @property
    def stats(self) -> CoordinatorStats:
        """Get coordinator statistics."""
        return self._stats

    def register_worker(
        self,
        transfer_type: TransferType,
        worker: WorkerProtocol,
    ) -> None:
        """Register a worker for a transfer type.

        Args:
            transfer_type: The type of transfers this worker handles
            worker: The worker instance
        """
        self._workers[transfer_type] = worker
        logger.debug("Registered worker for %s", transfer_type.name)

    def set_on_transfer_complete(
        self,
        callback: Callable[[TransferState], None],
    ) -> None:
        """Set callback for transfer completion."""
        self._on_transfer_complete = callback

    def set_on_conflict(
        self,
        callback: Callable[[str, SyncEvent, SyncEvent], None],
    ) -> None:
        """Set callback for conflict detection.

        Args:
            callback: Function(path, local_event, remote_event)
        """
        self._on_conflict = callback

    def start(self) -> None:
        """Start the coordinator processing thread."""
        with self._lock:
            if self._state != CoordinatorState.STOPPED:
                logger.warning("Coordinator already running")
                return

            self._state = CoordinatorState.RUNNING
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run,
                name="SyncCoordinator",
                daemon=True,
            )
            self._thread.start()
            logger.info("Coordinator started")

    def stop(self, timeout: float = 5.0) -> None:
        """Stop the coordinator.

        Args:
            timeout: Maximum time to wait for thread to stop
        """
        with self._lock:
            if self._state == CoordinatorState.STOPPED:
                return

            self._state = CoordinatorState.STOPPING
            self._stop_event.set()  # Signal the thread to stop
            logger.info("Coordinator stopping...")

            # Cancel all in-progress transfers
            for transfer in self._transfers.values():
                if transfer.status == TransferStatus.IN_PROGRESS:
                    transfer.request_cancel()

        # Wait for thread to finish
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)

        with self._lock:
            self._state = CoordinatorState.STOPPED
            self._thread = None
            logger.info("Coordinator stopped")

    def get_transfer(self, path: str) -> TransferState | None:
        """Get the current transfer state for a path.

        Args:
            path: The file path

        Returns:
            TransferState if there's an active transfer, None otherwise
        """
        with self._lock:
            return self._transfers.get(path)

    def get_active_transfers(self) -> list[TransferState]:
        """Get all active (in-progress) transfers."""
        with self._lock:
            return [
                t for t in self._transfers.values()
                if t.status == TransferStatus.IN_PROGRESS
            ]

    def cancel_transfer(self, path: str) -> bool:
        """Request cancellation of a transfer.

        Args:
            path: The file path to cancel

        Returns:
            True if cancellation was requested, False if no active transfer
        """
        with self._lock:
            transfer = self._transfers.get(path)
            if transfer and transfer.status == TransferStatus.IN_PROGRESS:
                transfer.request_cancel()
                return True
            return False

    def _run(self) -> None:
        """Main processing loop."""
        logger.debug("Coordinator processing loop started")

        while self._state == CoordinatorState.RUNNING and not self._stop_event.is_set():
            try:
                # Get next event (with short timeout to check stop event)
                event = self._queue.get(timeout=0.1)
                if event is None:
                    continue

                self._process_event(event)

            except Exception:
                logger.exception("Error processing event")
                self._stats.errors += 1

        logger.debug("Coordinator processing loop ended")

    def _process_event(self, event: SyncEvent) -> None:
        """Process a single event.

        This is where the decision matrix is applied.

        Args:
            event: The event to process
        """
        logger.debug("Processing event: %s", event)
        self._stats.events_processed += 1

        with self._lock:
            # Check for existing transfer on this path
            existing = self._transfers.get(event.path)

            if existing and existing.status == TransferStatus.IN_PROGRESS:
                # Apply decision matrix for concurrent operations
                self._handle_concurrent(event, existing)
            else:
                # No concurrent operation, dispatch normally
                self._dispatch(event)

    def _handle_concurrent(
        self,
        new_event: SyncEvent,
        existing: TransferState,
    ) -> None:
        """Handle concurrent events on the same path.

        Args:
            new_event: The new incoming event
            existing: The existing in-progress transfer
        """
        logger.info(
            "Concurrent event on %s: new=%s, existing=%s",
            new_event.path,
            new_event.event_type.name,
            existing.transfer_type.name,
        )

        # Decision matrix implementation
        if new_event.source == SyncEventSource.LOCAL:
            # Local event while transfer in progress
            if existing.transfer_type == TransferType.DOWNLOAD:
                # LOCAL_* while DOWNLOAD -> Cancel download, process local event
                logger.info(
                    "Cancelling download of %s due to local %s",
                    new_event.path,
                    new_event.event_type.name,
                )
                existing.request_cancel()
                self._stats.transfers_cancelled += 1

                # Re-queue the new event (will be processed after cancel completes)
                self._queue.put(new_event)

            elif existing.transfer_type == TransferType.UPLOAD:
                # LOCAL_* while UPLOAD -> Just update metadata, upload continues
                logger.debug(
                    "Local event on %s while upload in progress, ignoring",
                    new_event.path,
                )

        elif new_event.source == SyncEventSource.REMOTE:
            # Remote event while transfer in progress
            if existing.transfer_type == TransferType.UPLOAD:
                # REMOTE_MODIFIED while UPLOAD -> Potential conflict
                logger.warning(
                    "Potential conflict on %s: upload in progress, remote modified",
                    new_event.path,
                )
                self._stats.conflicts_detected += 1

                if self._on_conflict:
                    self._on_conflict(new_event.path, existing.event, new_event)

            elif existing.transfer_type == TransferType.DOWNLOAD:
                # REMOTE_* while DOWNLOAD -> Just continue, newer version
                logger.debug(
                    "Remote event on %s while download in progress, continuing",
                    new_event.path,
                )

    def _dispatch(self, event: SyncEvent) -> None:
        """Dispatch an event to the appropriate worker.

        Args:
            event: The event to dispatch
        """
        # Determine transfer type based on event
        transfer_type = self._event_to_transfer_type(event)
        if transfer_type is None:
            logger.debug("No action needed for event: %s", event)
            return

        # Check if we have a worker for this type
        worker = self._workers.get(transfer_type)
        if worker is None:
            logger.warning("No worker registered for %s", transfer_type.name)
            return

        # Create transfer state
        transfer = TransferState(
            path=event.path,
            transfer_type=transfer_type,
            status=TransferStatus.IN_PROGRESS,
            event=event,
        )
        self._transfers[event.path] = transfer

        logger.info(
            "Starting %s for %s",
            transfer_type.name,
            event.path,
        )

        # Execute in current thread (for now - Phase 15.3 will add worker pool)
        try:
            success = worker.execute(
                event=event,
                cancel_check=lambda: transfer.cancel_requested,
            )

            if transfer.cancel_requested:
                transfer.status = TransferStatus.CANCELLED
                logger.info("Transfer cancelled: %s", event.path)
            elif success:
                transfer.status = TransferStatus.COMPLETED
                self._update_stats_on_complete(transfer_type)
                logger.info("Transfer completed: %s", event.path)
            else:
                transfer.status = TransferStatus.FAILED
                self._stats.errors += 1
                logger.error("Transfer failed: %s", event.path)

        except Exception as e:
            transfer.status = TransferStatus.FAILED
            transfer.error = str(e)
            self._stats.errors += 1
            logger.exception("Transfer error: %s", event.path)

        finally:
            # Notify completion
            if self._on_transfer_complete:
                self._on_transfer_complete(transfer)

            # Clean up completed transfers (keep for debugging)
            # In production, we might want to keep a history

    def _event_to_transfer_type(self, event: SyncEvent) -> TransferType | None:
        """Map event type to transfer type.

        Args:
            event: The sync event

        Returns:
            TransferType or None if no action needed
        """
        mapping = {
            SyncEventType.LOCAL_CREATED: TransferType.UPLOAD,
            SyncEventType.LOCAL_MODIFIED: TransferType.UPLOAD,
            SyncEventType.LOCAL_DELETED: TransferType.DELETE,
            SyncEventType.REMOTE_CREATED: TransferType.DOWNLOAD,
            SyncEventType.REMOTE_MODIFIED: TransferType.DOWNLOAD,
            SyncEventType.REMOTE_DELETED: TransferType.DELETE,
        }
        return mapping.get(event.event_type)

    def _update_stats_on_complete(self, transfer_type: TransferType) -> None:
        """Update statistics after successful transfer."""
        if transfer_type == TransferType.UPLOAD:
            self._stats.uploads_completed += 1
        elif transfer_type == TransferType.DOWNLOAD:
            self._stats.downloads_completed += 1
        elif transfer_type == TransferType.DELETE:
            self._stats.deletes_completed += 1
