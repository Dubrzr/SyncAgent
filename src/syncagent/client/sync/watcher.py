"""File system watcher with debouncing for sync detection.

This module provides:
- FileWatcher: Watches a directory for changes using watchdog
- Debouncing: Coalesces rapid events (250ms window)
- Sync delay: Waits 3s after last change before triggering sync
- Ignore patterns: Respects .syncignore patterns
- Direct EventQueue integration (optional)
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING

from watchdog.events import (
    DirCreatedEvent,
    DirDeletedEvent,
    DirModifiedEvent,
    DirMovedEvent,
    FileCreatedEvent,
    FileDeletedEvent,
    FileModifiedEvent,
    FileMovedEvent,
    FileSystemEvent,
    FileSystemEventHandler,
)
from watchdog.observers import Observer

if TYPE_CHECKING:
    from watchdog.observers.api import BaseObserver

    from syncagent.client.sync.queue import EventQueue

logger = logging.getLogger(__name__)


class ChangeType(Enum):
    """Type of file system change."""

    CREATED = "created"
    MODIFIED = "modified"
    DELETED = "deleted"
    MOVED = "moved"


@dataclass
class FileChange:
    """Represents a file system change event."""

    path: Path
    change_type: ChangeType
    is_directory: bool
    timestamp: float = field(default_factory=time.time)
    dest_path: Path | None = None  # For MOVED events


# Default ignore patterns (similar to common .gitignore entries)
DEFAULT_IGNORE_PATTERNS = [
    ".git",
    ".git/**",
    ".DS_Store",
    "Thumbs.db",
    "*.tmp",
    "*.temp",
    "~*",
    "*.swp",
    "*.swo",
    ".syncagent",
    ".syncagent/**",
]


class IgnorePatterns:
    """Handles ignore pattern matching for file paths."""

    def __init__(self, patterns: list[str] | None = None) -> None:
        """Initialize with patterns.

        Args:
            patterns: List of gitignore-style patterns.
        """
        self._patterns = list(DEFAULT_IGNORE_PATTERNS)
        if patterns:
            self._patterns.extend(patterns)

    def add_pattern(self, pattern: str) -> None:
        """Add an ignore pattern."""
        self._patterns.append(pattern)

    def load_from_file(self, path: Path) -> None:
        """Load patterns from a .syncignore file."""
        if path.exists():
            with open(path, encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    # Skip comments and empty lines
                    if line and not line.startswith("#"):
                        self._patterns.append(line)

    def should_ignore(self, path: Path, base_path: Path) -> bool:
        """Check if a path should be ignored.

        Args:
            path: Absolute path to check.
            base_path: Base sync directory path.

        Returns:
            True if the path should be ignored.
        """
        # Always ignore symlinks (SC-22)
        if path.is_symlink():
            return True

        try:
            rel_path = path.relative_to(base_path)
        except ValueError:
            return False

        rel_str = str(rel_path).replace("\\", "/")

        for pattern in self._patterns:
            # Handle directory-only patterns (ending with /)
            if pattern.endswith("/"):
                pattern = pattern[:-1]
                if path.is_dir() and fnmatch.fnmatch(rel_str, pattern):
                    return True
                # Also match if any parent matches
                if fnmatch.fnmatch(rel_str.split("/")[0], pattern):
                    return True
            # Handle ** patterns
            elif "**" in pattern:
                # Simple glob match for **
                if fnmatch.fnmatch(rel_str, pattern):
                    return True
            # Standard pattern or filename match
            elif fnmatch.fnmatch(rel_str, pattern) or fnmatch.fnmatch(path.name, pattern):
                return True

        return False


class DebouncedEventHandler(FileSystemEventHandler):
    """Event handler that debounces rapid file system events."""

    def __init__(
        self,
        base_path: Path,
        on_changes: Callable[[list[FileChange]], None],
        debounce_ms: int = 250,
        sync_delay_s: float = 3.0,
        ignore_patterns: IgnorePatterns | None = None,
    ) -> None:
        """Initialize the debounced handler.

        Args:
            base_path: Base directory being watched.
            on_changes: Callback when changes are ready to sync.
            debounce_ms: Debounce window in milliseconds.
            sync_delay_s: Delay after last change before triggering sync.
            ignore_patterns: Patterns for files to ignore.
        """
        super().__init__()
        self._base_path = base_path
        self._on_changes = on_changes
        self._debounce_ms = debounce_ms
        self._sync_delay_s = sync_delay_s
        self._ignore = ignore_patterns or IgnorePatterns()

        # Pending changes keyed by path
        self._pending: dict[str, FileChange] = {}
        self._lock = threading.Lock()
        self._timer: threading.Timer | None = None
        self._last_event_time: float = 0.0

    def _schedule_flush(self) -> None:
        """Schedule a flush of pending changes after sync delay."""
        if self._timer:
            self._timer.cancel()

        self._timer = threading.Timer(self._sync_delay_s, self._flush_changes)
        self._timer.daemon = True
        self._timer.start()

    def _flush_changes(self) -> None:
        """Flush pending changes to the callback."""
        with self._lock:
            if not self._pending:
                return

            changes = list(self._pending.values())
            self._pending.clear()
            self._timer = None

        # Call callback outside lock
        if changes:
            self._on_changes(changes)

    def _handle_event(self, event: FileSystemEvent) -> None:
        """Handle a file system event with debouncing."""
        src_path = event.src_path
        if isinstance(src_path, bytes):
            src_path = src_path.decode("utf-8", errors="replace")
        path = Path(src_path)

        # Skip ignored files
        if self._ignore.should_ignore(path, self._base_path):
            return

        now = time.time()

        # Determine change type
        if isinstance(event, FileCreatedEvent | DirCreatedEvent):
            change_type = ChangeType.CREATED
        elif isinstance(event, FileModifiedEvent | DirModifiedEvent):
            change_type = ChangeType.MODIFIED
        elif isinstance(event, FileDeletedEvent | DirDeletedEvent):
            change_type = ChangeType.DELETED
        elif isinstance(event, FileMovedEvent | DirMovedEvent):
            change_type = ChangeType.MOVED
        else:
            return

        is_directory = isinstance(
            event,
            DirCreatedEvent | DirModifiedEvent | DirDeletedEvent | DirMovedEvent,
        )

        dest_path = None
        if isinstance(event, FileMovedEvent | DirMovedEvent):
            dest = event.dest_path
            if isinstance(dest, bytes):
                dest = dest.decode("utf-8", errors="replace")
            dest_path = Path(dest)

        change = FileChange(
            path=path,
            change_type=change_type,
            is_directory=is_directory,
            timestamp=now,
            dest_path=dest_path,
        )

        with self._lock:
            key = str(path)

            # Debounce: check if we recently saw an event for this path
            if key in self._pending:
                time_diff = (now - self._pending[key].timestamp) * 1000
                if time_diff < self._debounce_ms:
                    # Update existing change
                    self._pending[key] = change
                    self._last_event_time = now
                    self._schedule_flush()
                    return

            self._pending[key] = change
            self._last_event_time = now
            self._schedule_flush()

    def on_created(self, event: FileSystemEvent) -> None:
        """Handle created event."""
        self._handle_event(event)

    def on_modified(self, event: FileSystemEvent) -> None:
        """Handle modified event."""
        self._handle_event(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        """Handle deleted event."""
        self._handle_event(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        """Handle moved event."""
        self._handle_event(event)

    def stop(self) -> None:
        """Stop any pending timers."""
        if self._timer:
            self._timer.cancel()
            self._timer = None


class FileWatcher:
    """Watches a directory for file changes with debouncing.

    Can operate in two modes:
    1. Callback mode: Calls on_changes with list of FileChange objects
    2. Queue mode: Injects SyncEvent objects directly into an EventQueue

    Queue mode is preferred for the event-driven architecture (Phase 15+).
    """

    def __init__(
        self,
        watch_path: Path,
        on_changes: Callable[[list[FileChange]], None] | None = None,
        debounce_ms: int = 250,
        sync_delay_s: float = 3.0,
        ignore_patterns: list[str] | None = None,
        *,
        event_queue: EventQueue | None = None,
    ) -> None:
        """Initialize the file watcher.

        Args:
            watch_path: Directory to watch.
            on_changes: Callback when changes are ready to sync (callback mode).
            debounce_ms: Debounce window in milliseconds.
            sync_delay_s: Delay after last change before triggering sync.
            ignore_patterns: Additional patterns to ignore.
            event_queue: EventQueue to inject events into (queue mode).

        Note:
            Either on_changes or event_queue must be provided.
            If both are provided, event_queue takes precedence.
        """
        self._watch_path = Path(watch_path).resolve()
        if not self._watch_path.is_dir():
            raise ValueError(f"Watch path must be a directory: {watch_path}")

        self._event_queue = event_queue
        self._on_changes_callback = on_changes

        # Validate that at least one output is configured
        if event_queue is None and on_changes is None:
            raise ValueError("Either on_changes or event_queue must be provided")

        self._ignore = IgnorePatterns(ignore_patterns)
        # Load .syncignore if it exists
        syncignore_path = self._watch_path / ".syncignore"
        self._ignore.load_from_file(syncignore_path)

        # Create the appropriate callback
        if event_queue is not None:
            callback = self._create_queue_callback()
        else:
            assert on_changes is not None  # For type checker
            callback = on_changes

        self._handler = DebouncedEventHandler(
            base_path=self._watch_path,
            on_changes=callback,
            debounce_ms=debounce_ms,
            sync_delay_s=sync_delay_s,
            ignore_patterns=self._ignore,
        )

        self._observer: BaseObserver = Observer()
        self._running = False

    def _create_queue_callback(self) -> Callable[[list[FileChange]], None]:
        """Create a callback that injects events into the queue."""
        from syncagent.client.sync.queue import (
            SyncEvent,
            SyncEventSource,
            SyncEventType,
        )

        def on_changes(changes: list[FileChange]) -> None:
            assert self._event_queue is not None

            for change in changes:
                # Skip directories - we only sync files
                if change.is_directory:
                    continue

                # Convert ChangeType to SyncEventType
                type_mapping = {
                    ChangeType.CREATED: SyncEventType.LOCAL_CREATED,
                    ChangeType.MODIFIED: SyncEventType.LOCAL_MODIFIED,
                    ChangeType.DELETED: SyncEventType.LOCAL_DELETED,
                }
                event_type = type_mapping.get(
                    change.change_type, SyncEventType.LOCAL_MODIFIED
                )

                # Compute relative path
                try:
                    rel_path = change.path.relative_to(self._watch_path)
                except ValueError:
                    logger.warning(
                        "Path %s is not relative to %s",
                        change.path,
                        self._watch_path,
                    )
                    continue

                # Use forward slashes for consistency
                path_str = str(rel_path).replace("\\", "/")

                event = SyncEvent.create(
                    event_type=event_type,
                    path=path_str,
                    source=SyncEventSource.LOCAL,
                    metadata={
                        "absolute_path": str(change.path),
                        "timestamp": change.timestamp,
                    },
                )
                self._event_queue.put(event)
                logger.debug("Watcher injected event: %s", event)

        return on_changes

    @property
    def watch_path(self) -> Path:
        """Get the watched directory path."""
        return self._watch_path

    @property
    def event_queue(self) -> EventQueue | None:
        """Get the event queue (if in queue mode)."""
        return self._event_queue

    @property
    def is_running(self) -> bool:
        """Check if the watcher is running."""
        return self._running

    def start(self) -> None:
        """Start watching for changes."""
        if self._running:
            return

        self._observer.schedule(self._handler, str(self._watch_path), recursive=True)
        self._observer.start()
        self._running = True

    def stop(self) -> None:
        """Stop watching for changes."""
        if not self._running:
            return

        self._handler.stop()
        self._observer.stop()
        self._observer.join(timeout=5.0)
        self._running = False

    def __enter__(self) -> FileWatcher:
        """Context manager entry."""
        self.start()
        return self

    def __exit__(self, *args: object) -> None:
        """Context manager exit."""
        self.stop()
