"""Conflict detection and resolution utilities.

This module provides:
- get_machine_name: Get registered machine name from config
- generate_conflict_filename: Generate conflict copy filename
"""

from __future__ import annotations

import socket
from datetime import datetime
from pathlib import Path


def get_machine_name() -> str:
    """Get the machine name for conflict file naming.

    Returns the registered machine name from config if available,
    otherwise falls back to the hostname (sanitized).

    Returns:
        Machine name (already safe for filenames if from config).
    """
    # Import here to avoid circular imports
    from syncagent.client.cli import get_registered_machine_name, sanitize_machine_name

    # Try to get registered name from config
    registered_name = get_registered_machine_name()
    if registered_name:
        return registered_name

    # Fallback to hostname (sanitized) if not registered
    return sanitize_machine_name(socket.gethostname())


def generate_conflict_filename(original_path: Path, machine_name: str | None = None) -> Path:
    """Generate a conflict filename with timestamp and machine name.

    Format: filename.conflict-YYYYMMDD-HHMMSS-{machine}.ext

    Args:
        original_path: Original file path.
        machine_name: Machine name (defaults to registered name from config).

    Returns:
        Path with conflict naming.
    """
    # Import here to avoid circular imports
    from syncagent.client.cli import sanitize_machine_name

    # get_machine_name() returns already sanitized names, but explicit names need sanitizing
    machine_name = get_machine_name() if machine_name is None else sanitize_machine_name(machine_name)

    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    stem = original_path.stem
    suffix = original_path.suffix

    new_name = f"{stem}.conflict-{timestamp}-{machine_name}{suffix}"
    return original_path.parent / new_name
