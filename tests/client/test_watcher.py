"""Tests for file system watcher with debouncing."""

import time
from pathlib import Path
from threading import Event
from typing import Any

import pytest

from syncagent.client.watcher import (
    ChangeType,
    FileChange,
    FileWatcher,
    IgnorePatterns,
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
            change_type=ChangeType.CREATED,
            is_directory=False,
        )

        assert change.path == path
        assert change.change_type == ChangeType.CREATED
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
    """Tests for FileWatcher class."""

    @pytest.fixture
    def watch_dir(self, tmp_path: Path) -> Path:
        """Create a watch directory."""
        watch = tmp_path / "sync"
        watch.mkdir()
        return watch

    def test_create_watcher(self, watch_dir: Path) -> None:
        """Should create a watcher for a directory."""
        changes: list[FileChange] = []
        watcher = FileWatcher(watch_dir, lambda c: changes.extend(c))

        assert watcher.watch_path == watch_dir.resolve()
        assert watcher.is_running is False

    def test_watcher_requires_directory(self, tmp_path: Path) -> None:
        """Should raise if path is not a directory."""
        file_path = tmp_path / "file.txt"
        file_path.touch()

        with pytest.raises(ValueError, match="must be a directory"):
            FileWatcher(file_path, lambda c: None)

    def test_start_stop(self, watch_dir: Path) -> None:
        """Should start and stop cleanly."""
        watcher = FileWatcher(watch_dir, lambda c: None)

        watcher.start()
        assert watcher.is_running is True

        watcher.stop()
        assert watcher.is_running is False

    def test_context_manager(self, watch_dir: Path) -> None:
        """Should work as context manager."""
        with FileWatcher(watch_dir, lambda c: None) as watcher:
            assert watcher.is_running is True
        assert watcher.is_running is False

    def test_detects_file_creation(self, watch_dir: Path) -> None:
        """Should detect when a file is created."""
        changes: list[FileChange] = []
        event = Event()

        def on_changes(c: list[FileChange]) -> None:
            changes.extend(c)
            event.set()

        with FileWatcher(watch_dir, on_changes, sync_delay_s=0.1):
            # Create a file
            test_file = watch_dir / "newfile.txt"
            test_file.write_text("hello")

            # Wait for callback
            assert event.wait(timeout=2.0), "Timeout waiting for changes"

        assert len(changes) >= 1
        # On Windows, creation may be reported as MODIFIED, so check for either
        file_changes = [c for c in changes if c.path.name == "newfile.txt"]
        assert len(file_changes) >= 1
        assert file_changes[0].change_type in (ChangeType.CREATED, ChangeType.MODIFIED)

    def test_detects_file_modification(self, watch_dir: Path) -> None:
        """Should detect when a file is modified."""
        # Create file first
        test_file = watch_dir / "existing.txt"
        test_file.write_text("initial")

        changes: list[FileChange] = []
        event = Event()

        def on_changes(c: list[FileChange]) -> None:
            changes.extend(c)
            event.set()

        with FileWatcher(watch_dir, on_changes, sync_delay_s=0.1):
            # Small delay to let watcher initialize
            time.sleep(0.1)

            # Modify the file
            test_file.write_text("modified content")

            # Wait for callback
            assert event.wait(timeout=2.0), "Timeout waiting for changes"

        assert len(changes) >= 1
        modified = [c for c in changes if c.change_type == ChangeType.MODIFIED]
        assert any(c.path.name == "existing.txt" for c in modified)

    def test_detects_file_deletion(self, watch_dir: Path) -> None:
        """Should detect when a file is deleted."""
        # Create file first
        test_file = watch_dir / "todelete.txt"
        test_file.write_text("content")

        changes: list[FileChange] = []
        event = Event()

        def on_changes(c: list[FileChange]) -> None:
            changes.extend(c)
            event.set()

        with FileWatcher(watch_dir, on_changes, sync_delay_s=0.1):
            time.sleep(0.2)  # Wait for watcher to be ready

            # Delete the file
            test_file.unlink()

            # Wait for deletion to be detected (may take longer on some platforms)
            timeout = 3.0
            start = time.time()
            while time.time() - start < timeout:
                if any(c.change_type == ChangeType.DELETED for c in changes):
                    break
                event.wait(timeout=0.5)

        deleted = [c for c in changes if c.change_type == ChangeType.DELETED]
        assert any(c.path.name == "todelete.txt" for c in deleted)

    def test_ignores_tmp_files(self, watch_dir: Path) -> None:
        """Should not report changes for ignored files."""
        changes: list[FileChange] = []

        with FileWatcher(watch_dir, lambda c: changes.extend(c), sync_delay_s=0.1):
            # Create an ignored file
            tmp_file = watch_dir / "temp.tmp"
            tmp_file.write_text("temp")

            # Create a non-ignored file
            txt_file = watch_dir / "real.txt"
            txt_file.write_text("real")

            time.sleep(0.5)

        # Should have changes for real.txt but not temp.tmp
        paths = [c.path.name for c in changes]
        assert "real.txt" in paths
        assert "temp.tmp" not in paths

    def test_debouncing(self, watch_dir: Path) -> None:
        """Should debounce rapid changes to same file."""
        changes: list[FileChange] = []
        event = Event()

        def on_changes(c: list[FileChange]) -> None:
            changes.extend(c)
            event.set()

        test_file = watch_dir / "rapid.txt"

        with FileWatcher(watch_dir, on_changes, debounce_ms=250, sync_delay_s=0.5):
            # Rapid writes
            for i in range(5):
                test_file.write_text(f"content {i}")
                time.sleep(0.05)  # 50ms between writes

            assert event.wait(timeout=3.0), "Timeout waiting for changes"

        # Should be coalesced into fewer changes (not 5)
        rapid_changes = [c for c in changes if c.path.name == "rapid.txt"]
        # Due to debouncing, we expect fewer events than the 5 writes
        assert len(rapid_changes) <= 3

    def test_sync_delay(self, watch_dir: Path) -> None:
        """Should wait sync_delay after last change before triggering."""
        callback_time: list[float] = []
        event = Event()

        def on_changes(c: list[Any]) -> None:
            callback_time.append(time.time())
            event.set()

        test_file = watch_dir / "delayed.txt"
        start_time = time.time()

        with FileWatcher(watch_dir, on_changes, sync_delay_s=0.5):
            test_file.write_text("content")

            assert event.wait(timeout=3.0), "Timeout waiting for changes"

        # Callback should happen ~0.5s after the write
        assert len(callback_time) == 1
        delay = callback_time[0] - start_time
        assert delay >= 0.4  # At least 0.4s delay (allowing some tolerance)

    def test_subdirectory_changes(self, watch_dir: Path) -> None:
        """Should detect changes in subdirectories."""
        changes: list[FileChange] = []
        event = Event()

        def on_changes(c: list[FileChange]) -> None:
            changes.extend(c)
            event.set()

        subdir = watch_dir / "subdir"
        subdir.mkdir()

        with FileWatcher(watch_dir, on_changes, sync_delay_s=0.1):
            # Create file in subdirectory
            nested_file = subdir / "nested.txt"
            nested_file.write_text("nested content")

            assert event.wait(timeout=2.0), "Timeout waiting for changes"

        assert any(c.path.name == "nested.txt" for c in changes)

    def test_loads_syncignore(self, watch_dir: Path) -> None:
        """Should load .syncignore from watch directory."""
        # Create .syncignore
        syncignore = watch_dir / ".syncignore"
        syncignore.write_text("*.ignored\n")

        changes: list[FileChange] = []

        with FileWatcher(watch_dir, lambda c: changes.extend(c), sync_delay_s=0.1):
            # Create ignored file
            ignored = watch_dir / "test.ignored"
            ignored.write_text("ignored")

            # Create normal file
            normal = watch_dir / "test.txt"
            normal.write_text("normal")

            time.sleep(0.5)

        paths = [c.path.name for c in changes]
        assert "test.txt" in paths
        assert "test.ignored" not in paths
