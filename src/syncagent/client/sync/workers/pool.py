"""Worker pool for concurrent transfer operations.

This module provides:
- WorkerPool: Manages a pool of workers for concurrent uploads/downloads
- WorkerTask: Represents a queued task for the pool
"""

from __future__ import annotations

import logging
import os
import queue
import threading
import time
from dataclasses import dataclass, field
from enum import Enum, auto
from pathlib import Path
from typing import TYPE_CHECKING

from syncagent.client.sync.domain.transfers import TransferType
from syncagent.client.sync.retry import NETWORK_EXCEPTIONS, wait_for_network
from syncagent.client.sync.types import SyncEvent
from syncagent.client.sync.workers.base import BaseWorker, WorkerResult
from syncagent.client.sync.workers.delete_worker import DeleteWorker
from syncagent.client.sync.workers.download_worker import DownloadWorker
from syncagent.client.sync.workers.upload_worker import UploadWorker

if TYPE_CHECKING:
    from collections.abc import Callable

    from syncagent.client.api import HTTPClient
    from syncagent.client.state import LocalSyncState

logger = logging.getLogger(__name__)


class PoolState(Enum):
    """State of the worker pool."""

    STOPPED = auto()
    RUNNING = auto()
    STOPPING = auto()


@dataclass
class WorkerTask:
    """A task to be executed by the worker pool.

    Attributes:
        event: The sync event to process.
        transfer_type: Type of transfer operation.
        on_complete: Callback when task completes successfully.
        on_error: Callback when task fails.
        on_progress: Optional progress callback.
    """

    event: SyncEvent
    transfer_type: TransferType
    on_complete: Callable[[WorkerResult], None] | None = None
    on_error: Callable[[str], None] | None = None
    on_progress: Callable[[int, int], None] | None = None
    cancel_requested: bool = field(default=False)

    def request_cancel(self) -> None:
        """Request cancellation of this task."""
        self.cancel_requested = True


class WorkerPool:
    """Pool of workers for concurrent transfer operations.

    Manages worker threads that process tasks from a queue. Each task
    is assigned to a worker thread for execution.

    Usage:
        pool = WorkerPool(client, key, base_path)  # Uses CPU count
        pool.start()

        # Submit tasks
        pool.submit(event, TransferType.UPLOAD, on_complete=callback)

        # Stop when done
        pool.stop()
    """

    def __init__(
        self,
        client: HTTPClient,
        encryption_key: bytes,
        base_path: Path,
        state: LocalSyncState | None = None,
        max_workers: int | None = None,
    ) -> None:
        """Initialize the worker pool.

        Args:
            client: HTTP client for server communication.
            encryption_key: 32-byte AES key for encryption/decryption.
            base_path: Base directory for resolving relative paths.
            state: Optional SyncState for tracking progress.
            max_workers: Maximum concurrent workers. Defaults to CPU count.
        """
        self._client = client
        self._key = encryption_key
        self._base_path = base_path
        self._state = state
        self._max_workers = max_workers or max(os.cpu_count() or 4, 2)

        # Pool state
        self._pool_state = PoolState.STOPPED
        self._lock = threading.Lock()

        # Task queue
        self._task_queue: queue.Queue[WorkerTask | None] = queue.Queue()

        # Active tasks by path (for cancellation)
        self._active_tasks: dict[str, WorkerTask] = {}

        # Worker threads
        self._workers: list[threading.Thread] = []

        # Statistics
        self._completed_count = 0
        self._error_count = 0

        # Speed tracking
        self._upload_bytes: list[tuple[float, int]] = []  # (timestamp, bytes)
        self._download_bytes: list[tuple[float, int]] = []
        self._speed_window = 5.0  # Calculate speed over 5 seconds

        # Active transfer counts
        self._active_uploads = 0
        self._active_downloads = 0
        self._active_hashing = 0

    @property
    def state(self) -> PoolState:
        """Get current pool state."""
        return self._pool_state

    @property
    def active_count(self) -> int:
        """Get number of active tasks."""
        with self._lock:
            return len(self._active_tasks)

    @property
    def queue_size(self) -> int:
        """Get number of queued tasks."""
        return self._task_queue.qsize()

    @property
    def completed_count(self) -> int:
        """Get number of completed tasks."""
        return self._completed_count

    @property
    def error_count(self) -> int:
        """Get number of failed tasks."""
        return self._error_count

    @property
    def active_uploads(self) -> int:
        """Get number of active upload tasks."""
        with self._lock:
            return self._active_uploads

    @property
    def active_downloads(self) -> int:
        """Get number of active download tasks."""
        with self._lock:
            return self._active_downloads

    @property
    def active_hashing(self) -> int:
        """Get number of files currently being hashed."""
        with self._lock:
            return self._active_hashing

    @property
    def upload_speed(self) -> int:
        """Get current upload speed in bytes/sec."""
        return self._calculate_speed(self._upload_bytes)

    @property
    def download_speed(self) -> int:
        """Get current download speed in bytes/sec."""
        return self._calculate_speed(self._download_bytes)

    def _calculate_speed(self, samples: list[tuple[float, int]]) -> int:
        """Calculate speed from byte samples.

        Args:
            samples: List of (timestamp, bytes) tuples.

        Returns:
            Speed in bytes/sec.
        """
        now = time.monotonic()
        cutoff = now - self._speed_window

        with self._lock:
            # Remove old samples
            while samples and samples[0][0] < cutoff:
                samples.pop(0)

            if not samples:
                return 0

            # Calculate bytes transferred in window
            total_bytes = sum(b for _, b in samples)

            # Use time since first sample, or time since single sample was recorded
            elapsed = (
                samples[-1][0] - samples[0][0]
                if len(samples) >= 2
                else now - samples[0][0]
            )

            # Ensure minimum elapsed time to avoid division issues
            elapsed = max(elapsed, 0.1)

            return int(total_bytes / elapsed)

    def _record_bytes(self, transfer_type: TransferType, byte_count: int) -> None:
        """Record bytes transferred for speed calculation.

        Args:
            transfer_type: Type of transfer (UPLOAD or DOWNLOAD).
            byte_count: Number of bytes transferred.
        """
        now = time.monotonic()
        with self._lock:
            if transfer_type == TransferType.UPLOAD:
                self._upload_bytes.append((now, byte_count))
            elif transfer_type == TransferType.DOWNLOAD:
                self._download_bytes.append((now, byte_count))

    def start(self) -> None:
        """Start the worker pool."""
        with self._lock:
            if self._pool_state != PoolState.STOPPED:
                logger.warning("Worker pool already running")
                return

            self._pool_state = PoolState.RUNNING

            # Start worker threads
            for i in range(self._max_workers):
                thread = threading.Thread(
                    target=self._worker_loop,
                    name=f"WorkerPool-{i}",
                    daemon=True,
                )
                thread.start()
                self._workers.append(thread)

            logger.info(f"Worker pool started with {self._max_workers} workers")

    def stop(self, timeout: float = 10.0) -> None:
        """Stop the worker pool.

        Args:
            timeout: Maximum time to wait for workers to finish.
        """
        with self._lock:
            if self._pool_state == PoolState.STOPPED:
                return

            self._pool_state = PoolState.STOPPING
            logger.info("Worker pool stopping...")

            # Cancel all active tasks
            for task in self._active_tasks.values():
                task.request_cancel()

            # Send poison pills to stop workers
            for _ in self._workers:
                self._task_queue.put(None)

        # Wait for workers to finish
        for worker in self._workers:
            worker.join(timeout=timeout / len(self._workers))

        with self._lock:
            self._pool_state = PoolState.STOPPED
            self._workers.clear()
            logger.info("Worker pool stopped")

    def submit(
        self,
        event: SyncEvent,
        transfer_type: TransferType,
        on_complete: Callable[[WorkerResult], None] | None = None,
        on_error: Callable[[str], None] | None = None,
        on_progress: Callable[[int, int], None] | None = None,
    ) -> bool:
        """Submit a task to the pool.

        Args:
            event: The sync event to process.
            transfer_type: Type of transfer operation.
            on_complete: Callback when task completes.
            on_error: Callback when task fails.
            on_progress: Optional progress callback.

        Returns:
            True if task was submitted, False if pool is not running.
        """
        if self._pool_state != PoolState.RUNNING:
            logger.warning("Cannot submit task: pool not running")
            return False

        task = WorkerTask(
            event=event,
            transfer_type=transfer_type,
            on_complete=on_complete,
            on_error=on_error,
            on_progress=on_progress,
        )

        self._task_queue.put(task)
        logger.debug(f"Task submitted: {transfer_type.name} {event.path}")
        return True

    def cancel(self, path: str) -> bool:
        """Cancel a task by path.

        Args:
            path: Path of the file to cancel.

        Returns:
            True if cancellation was requested, False if no active task.
        """
        with self._lock:
            task = self._active_tasks.get(path)
            if task:
                task.request_cancel()
                logger.info(f"Cancellation requested for: {path}")
                return True
            return False

    def _worker_loop(self) -> None:
        """Main loop for worker threads."""
        while self._pool_state == PoolState.RUNNING:
            try:
                # Get next task (blocks until available)
                task = self._task_queue.get(timeout=1.0)

                if task is None:
                    # Poison pill - stop worker
                    break

                self._process_task(task)

            except queue.Empty:
                continue
            except Exception:
                logger.exception("Unexpected error in worker loop")

    def _process_task(self, task: WorkerTask) -> None:
        """Process a single task with network-aware retry.

        On network errors, waits for network to recover and re-queues the task.

        Args:
            task: The task to process.
        """
        path = task.event.path
        transfer_type = task.transfer_type

        # Register as active and track upload/download counts
        with self._lock:
            self._active_tasks[path] = task
            if transfer_type == TransferType.UPLOAD:
                self._active_uploads += 1
            elif transfer_type == TransferType.DOWNLOAD:
                self._active_downloads += 1

        # Track last progress for delta calculation
        last_bytes = [0]  # Use list to allow mutation in closure

        # Hashing phase callbacks (for tracking hashing count)
        def on_hashing_start() -> None:
            with self._lock:
                self._active_hashing += 1

        def on_hashing_end() -> None:
            with self._lock:
                self._active_hashing -= 1

        def progress_wrapper(current: int, total: int) -> None:
            """Wrap progress callback to record bytes for speed calculation."""
            # Calculate delta since last progress update
            delta = current - last_bytes[0]
            if delta > 0:
                self._record_bytes(transfer_type, delta)
                last_bytes[0] = current

            # Call original callback if provided
            if task.on_progress:
                task.on_progress(current, total)

        try:
            # Create appropriate worker
            worker = self._create_worker(transfer_type)

            # Execute with wrapped progress callback and hashing callbacks
            success = worker.execute(
                event=task.event,
                on_progress=progress_wrapper,
                cancel_check=lambda: task.cancel_requested,
                on_hashing_start=on_hashing_start if transfer_type == TransferType.UPLOAD else None,
                on_hashing_end=on_hashing_end if transfer_type == TransferType.UPLOAD else None,
            )

            if success:
                self._completed_count += 1
                if task.on_complete:
                    # Get result from worker
                    result = WorkerResult(success=True)
                    task.on_complete(result)
            else:
                self._error_count += 1
                if task.on_error:
                    task.on_error(f"Task failed: {path}")

        except NETWORK_EXCEPTIONS as e:
            # Network error - wait for network and re-queue
            logger.warning(f"{transfer_type.name.lower()} worker failed: {e}")

            # Unregister from active before waiting
            with self._lock:
                self._active_tasks.pop(path, None)
                if transfer_type == TransferType.UPLOAD:
                    self._active_uploads -= 1
                elif transfer_type == TransferType.DOWNLOAD:
                    self._active_downloads -= 1

            # Don't retry if pool is stopping or task was cancelled
            if self._pool_state != PoolState.RUNNING or task.cancel_requested:
                if task.on_error:
                    task.on_error(str(e))
                return

            # Wait for network to recover (blocking)
            logger.info(f"Waiting for network to recover before retrying {path}...")
            wait_for_network(
                self._client,
                on_waiting=lambda: logger.debug("Still waiting for network..."),
                on_restored=lambda: logger.info("Network restored, retrying task"),
            )

            # Re-queue the task (reset progress tracking)
            if self._pool_state == PoolState.RUNNING:
                logger.info(f"Re-queuing task: {transfer_type.name} {path}")
                self._task_queue.put(task)
            return  # Skip the finally block's unregister (already done above)

        except Exception as e:
            self._error_count += 1
            logger.exception(f"Task error: {path}")
            if task.on_error:
                task.on_error(str(e))

        finally:
            # Unregister from active and update counts
            with self._lock:
                # Only unregister if still registered (network errors handle this above)
                if path in self._active_tasks:
                    self._active_tasks.pop(path, None)
                    if transfer_type == TransferType.UPLOAD:
                        self._active_uploads -= 1
                    elif transfer_type == TransferType.DOWNLOAD:
                        self._active_downloads -= 1

    def _create_worker(self, transfer_type: TransferType) -> BaseWorker:
        """Create a worker for the given transfer type.

        Args:
            transfer_type: Type of transfer.

        Returns:
            Appropriate worker instance.
        """
        if transfer_type == TransferType.UPLOAD:
            return UploadWorker(
                client=self._client,
                encryption_key=self._key,
                base_path=self._base_path,
                sync_state=self._state,
            )
        elif transfer_type == TransferType.DOWNLOAD:
            return DownloadWorker(
                client=self._client,
                encryption_key=self._key,
                base_path=self._base_path,
                sync_state=self._state,
            )
        elif transfer_type == TransferType.DELETE:
            return DeleteWorker(
                client=self._client,
                base_path=self._base_path,
                sync_state=self._state,
            )
        else:
            raise ValueError(f"Unknown transfer type: {transfer_type}")
