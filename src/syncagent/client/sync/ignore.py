"""Ignore patterns for file synchronization.

This module provides:
- IgnorePatterns: Handles gitignore-style pattern matching
- DEFAULT_IGNORE_PATTERNS: Common patterns to ignore
"""

from __future__ import annotations

import fnmatch
from pathlib import Path

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
