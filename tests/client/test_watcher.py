"""Tests for file system watcher with debouncing."""

import os
import time
from pathlib import Path

import pytest

from syncagent.client.sync.ignore import IgnorePatterns
from syncagent.client.sync.queue import EventQueue
from syncagent.client.sync.types import SyncEventType
from syncagent.client.sync.watcher import (
    ChangeType,
    FileChange,
    FileWatcher,
)


class TestIgnorePatterns:
    """Tests for ignore pattern matching."""

    def test_default_patterns(self, tmp_path: Path) -> None:
        """Should ignore default patterns like .git."""
        ignore = IgnorePatterns()
        git_path = tmp_path / ".git"
        git_path.mkdir()

        assert ignore.should_ignore(git_path, tmp_path) is True

    def test_ds_store_ignored(self, tmp_path: Path) -> None:
        """Should ignore .DS_Store files."""
        ignore = IgnorePatterns()
        ds_store = tmp_path / ".DS_Store"
        ds_store.touch()

        assert ignore.should_ignore(ds_store, tmp_path) is True

    def test_tmp_files_ignored(self, tmp_path: Path) -> None:
        """Should ignore .tmp files."""
        ignore = IgnorePatterns()
        tmp_file = tmp_path / "file.tmp"
        tmp_file.touch()

        assert ignore.should_ignore(tmp_file, tmp_path) is True

    def test_normal_file_not_ignored(self, tmp_path: Path) -> None:
        """Should not ignore normal files."""
        ignore = IgnorePatterns()
        normal_file = tmp_path / "document.txt"
        normal_file.touch()

        assert ignore.should_ignore(normal_file, tmp_path) is False

    def test_custom_pattern(self, tmp_path: Path) -> None:
        """Should support custom patterns."""
        ignore = IgnorePatterns(["*.log", "build/"])

        log_file = tmp_path / "app.log"
        log_file.touch()
        assert ignore.should_ignore(log_file, tmp_path) is True

        # Normal file not matched
        txt_file = tmp_path / "notes.txt"
        txt_file.touch()
        assert ignore.should_ignore(txt_file, tmp_path) is False

    def test_add_pattern(self, tmp_path: Path) -> None:
        """Should allow adding patterns dynamically."""
        ignore = IgnorePatterns()

        test_file = tmp_path / "test.xyz"
        test_file.touch()
        assert ignore.should_ignore(test_file, tmp_path) is False

        ignore.add_pattern("*.xyz")
        assert ignore.should_ignore(test_file, tmp_path) is True

    def test_load_from_file(self, tmp_path: Path) -> None:
        """Should load patterns from .syncignore file."""
        syncignore = tmp_path / ".syncignore"
        syncignore.write_text("*.bak\n# comment\ntemp/\n")

        ignore = IgnorePatterns()
        ignore.load_from_file(syncignore)

        bak_file = tmp_path / "backup.bak"
        bak_file.touch()
        assert ignore.should_ignore(bak_file, tmp_path) is True

    def test_load_missing_file(self, tmp_path: Path) -> None:
        """Should handle missing .syncignore gracefully."""
        ignore = IgnorePatterns()
        ignore.load_from_file(tmp_path / "nonexistent")
        # Should not raise

    def test_glob_pattern(self, tmp_path: Path) -> None:
        """Should support ** glob patterns."""
        ignore = IgnorePatterns([".git/**"])
        git_dir = tmp_path / ".git"
        git_dir.mkdir()
        objects = git_dir / "objects"
        objects.mkdir()

        assert ignore.should_ignore(objects, tmp_path) is True

    def test_syncagent_dir_ignored(self, tmp_path: Path) -> None:
        """Should ignore .syncagent directory."""
        ignore = IgnorePatterns()
        syncagent_dir = tmp_path / ".syncagent"
        syncagent_dir.mkdir()

        assert ignore.should_ignore(syncagent_dir, tmp_path) is True


class TestFileChange:
    """Tests for FileChange dataclass."""

    def test_create_change(self) -> None:
        """Should create a change with correct attributes."""
        path = Path("/test/file.txt")
        change = FileChange(
            path=path,
            change_type=ChangeType.MODIFIED,
            is_directory=False,
        )

        assert change.path == path
        assert change.change_type == ChangeType.MODIFIED
        assert change.is_directory is False
        assert change.dest_path is None
        assert change.timestamp > 0

    def test_moved_change(self) -> None:
        """Should handle moved events with dest_path."""
        src = Path("/test/old.txt")
        dest = Path("/test/new.txt")

        change = FileChange(
            path=src,
            change_type=ChangeType.MOVED,
            is_directory=False,
            dest_path=dest,
        )

        assert change.path == src
        assert change.dest_path == dest


class TestFileWatcher:
    """Tests for FileWatcher class (queue mode)."""

    @pytest.fixture
    def watch_dir(self, tmp_path: Path) -> Path:
        """Create a watch directory."""
        watch = tmp_path / "sync"
        watch.mkdir()
        return watch

    @pytest.fixture
    def event_queue(self) -> EventQueue:
        """Create an event queue."""
        return EventQueue()

    def test_create_watcher(self, watch_dir: Path, event_queue: EventQueue) -> None:
        """Should create a watcher for a directory."""
        watcher = FileWatcher(watch_dir, event_queue)

        assert watcher.watch_path == watch_dir.resolve()
        assert watcher.is_running is False
        assert watcher.event_queue is event_queue

    def test_watcher_requires_directory(
        self, tmp_path: Path, event_queue: EventQueue
    ) -> None:
        """Should raise if path is not a directory."""
        file_path = tmp_path / "file.txt"
        file_path.touch()

        with pytest.raises(ValueError, match="must be a directory"):
            FileWatcher(file_path, event_queue)

    def test_start_stop(self, watch_dir: Path, event_queue: EventQueue) -> None:
        """Should start and stop cleanly."""
        watcher = FileWatcher(watch_dir, event_queue)

        watcher.start()
        assert watcher.is_running is True

        watcher.stop()
        assert watcher.is_running is False

    def test_context_manager(self, watch_dir: Path, event_queue: EventQueue) -> None:
        """Should work as context manager."""
        with FileWatcher(watch_dir, event_queue) as watcher:
            assert watcher.is_running is True
        assert watcher.is_running is False

    def test_detects_file_creation(
        self, watch_dir: Path, event_queue: EventQueue
    ) -> None:
        """Should detect when a file is created and inject event."""
        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            # Create a file
            test_file = watch_dir / "newfile.txt"
            test_file.write_text("hello")

            # Wait for event
            event = event_queue.get(timeout=3.0)

        assert event is not None
        assert event.path == "newfile.txt"
        assert event.event_type in (SyncEventType.LOCAL_CREATED, SyncEventType.LOCAL_MODIFIED)

    def test_detects_file_modification(
        self, watch_dir: Path, event_queue: EventQueue
    ) -> None:
        """Should detect when a file is modified."""
        # Create file first
        test_file = watch_dir / "existing.txt"
        test_file.write_text("initial")

        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            time.sleep(0.1)  # Wait for watcher to initialize

            # Modify the file
            test_file.write_text("modified content")

            # Wait for event
            event = event_queue.get(timeout=3.0)

        assert event is not None
        assert event.path == "existing.txt"
        assert event.event_type == SyncEventType.LOCAL_MODIFIED

    def test_detects_file_deletion(
        self, watch_dir: Path, event_queue: EventQueue
    ) -> None:
        """Should detect when a file is deleted."""
        # Create file first
        test_file = watch_dir / "todelete.txt"
        test_file.write_text("content")

        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            time.sleep(0.2)  # Wait for watcher to be ready

            # Delete the file
            test_file.unlink()

            # Wait for deletion event (may take longer)
            event = event_queue.get(timeout=5.0)

        assert event is not None
        assert event.path == "todelete.txt"
        assert event.event_type == SyncEventType.LOCAL_DELETED

    def test_ignores_tmp_files(
        self, watch_dir: Path, event_queue: EventQueue
    ) -> None:
        """Should not inject events for ignored files."""
        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            # Create an ignored file
            tmp_file = watch_dir / "temp.tmp"
            tmp_file.write_text("temp")

            # Create a non-ignored file
            real_file = watch_dir / "real.txt"
            real_file.write_text("content")

            # Wait for event
            event = event_queue.get(timeout=3.0)

        assert event is not None
        # Should only see the non-ignored file
        assert event.path == "real.txt"

    def test_debouncing(self, watch_dir: Path, event_queue: EventQueue) -> None:
        """Should debounce rapid changes to the same file."""
        test_file = watch_dir / "rapid.txt"
        test_file.write_text("v1")

        with FileWatcher(watch_dir, event_queue, debounce_ms=250, sync_delay_s=0.5):
            time.sleep(0.1)  # Wait for watcher

            # Rapid modifications
            for i in range(5):
                test_file.write_text(f"version {i}")
                time.sleep(0.05)

            # Wait longer than debounce + sync delay
            time.sleep(1.0)

        # Should have coalesced to fewer events
        events = []
        while True:
            e = event_queue.get_nowait()
            if e is None:
                break
            events.append(e)

        # Due to debouncing, should have fewer events than modifications
        rapid_events = [e for e in events if e.path == "rapid.txt"]
        # Debouncing may result in 1-2 events instead of 5
        assert len(rapid_events) <= 3

    def test_subdirectory_changes(
        self, watch_dir: Path, event_queue: EventQueue
    ) -> None:
        """Should detect changes in subdirectories."""
        subdir = watch_dir / "subdir"
        subdir.mkdir()

        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            # Create file in subdirectory
            sub_file = subdir / "nested.txt"
            sub_file.write_text("nested content")

            # Wait for event
            event = event_queue.get(timeout=3.0)

        assert event is not None
        assert event.path == "subdir/nested.txt"

    def test_loads_syncignore(self, watch_dir: Path, event_queue: EventQueue) -> None:
        """Should load and respect .syncignore patterns."""
        # Create .syncignore
        syncignore = watch_dir / ".syncignore"
        syncignore.write_text("*.ignored\n")

        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            # Create an ignored file
            ignored_file = watch_dir / "test.ignored"
            ignored_file.write_text("should be ignored")

            # Create a normal file
            normal_file = watch_dir / "normal.txt"
            normal_file.write_text("should be detected")

            # Wait for event
            event = event_queue.get(timeout=3.0)

        assert event is not None
        assert event.path == "normal.txt"


class TestSymlinkExclusion:
    """Tests for symlink exclusion (SC-22)."""

    @pytest.fixture
    def watch_dir(self, tmp_path: Path) -> Path:
        """Create a watch directory."""
        watch = tmp_path / "sync"
        watch.mkdir()
        return watch

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require admin on Windows")
    def test_symlink_file_ignored(self, watch_dir: Path) -> None:
        """Should ignore symlinks to files."""
        ignore = IgnorePatterns()

        # Create a real file and a symlink
        real_file = watch_dir / "real.txt"
        real_file.write_text("content")

        symlink = watch_dir / "link.txt"
        symlink.symlink_to(real_file)

        assert ignore.should_ignore(real_file, watch_dir) is False
        assert ignore.should_ignore(symlink, watch_dir) is True

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require admin on Windows")
    def test_symlink_directory_ignored(self, watch_dir: Path) -> None:
        """Should ignore symlinks to directories."""
        ignore = IgnorePatterns()

        # Create a real directory and a symlink
        real_dir = watch_dir / "real_dir"
        real_dir.mkdir()

        symlink_dir = watch_dir / "link_dir"
        symlink_dir.symlink_to(real_dir, target_is_directory=True)

        assert ignore.should_ignore(real_dir, watch_dir) is False
        assert ignore.should_ignore(symlink_dir, watch_dir) is True

    @pytest.mark.skipif(os.name == "nt", reason="Symlinks require admin on Windows")
    def test_watcher_ignores_symlinks(self, watch_dir: Path) -> None:
        """Should not report changes for symlinked files."""
        event_queue = EventQueue()

        # Create a real file outside watch dir
        parent = watch_dir.parent
        external_file = parent / "external.txt"
        external_file.write_text("external content")

        # Create a symlink to it inside watch dir
        symlink = watch_dir / "linked.txt"
        symlink.symlink_to(external_file)

        with FileWatcher(watch_dir, event_queue, sync_delay_s=0.1):
            # Create a real file (should be detected)
            real_file = watch_dir / "real.txt"
            real_file.write_text("real content")

            # Modify through symlink (should be ignored)
            symlink.write_text("modified via symlink")

            time.sleep(0.5)

        # Only real.txt should have an event
        events = []
        while True:
            e = event_queue.get_nowait()
            if e is None:
                break
            events.append(e)

        real_events = [e for e in events if e.path == "real.txt"]
        assert len(real_events) >= 1

        linked_events = [e for e in events if e.path == "linked.txt"]
        assert len(linked_events) == 0
