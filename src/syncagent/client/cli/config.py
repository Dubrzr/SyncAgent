"""Configuration utilities for SyncAgent CLI.

This module provides shared configuration functions used across CLI commands.
"""

from __future__ import annotations

import json
from pathlib import Path


def get_config_dir() -> Path:
    """Get the configuration directory for SyncAgent.

    Returns:
        Path to ~/.syncagent or equivalent.
    """
    return Path.home() / ".syncagent"


def get_config_file() -> Path:
    """Get the path to the config file."""
    return get_config_dir() / "config.json"


def load_config() -> dict[str, str]:
    """Load configuration from config file."""
    config_file = get_config_file()
    if config_file.exists():
        return dict(json.loads(config_file.read_text()))
    return {}


def save_config(config: dict[str, str]) -> None:
    """Save configuration to config file."""
    config_file = get_config_file()
    config_file.parent.mkdir(parents=True, exist_ok=True)
    config_file.write_text(json.dumps(config, indent=2))


def get_sync_folder() -> Path:
    """Get the sync folder path.

    Returns:
        Path to the sync folder (configured or default ~/SyncAgent).
    """
    config = load_config()
    if config.get("sync_folder"):
        return Path(config["sync_folder"]).expanduser().resolve()
    return Path.home() / "SyncAgent"


def sanitize_machine_name(name: str) -> str:
    """Sanitize machine name to be safe for filenames.

    Only allows alphanumeric characters, hyphens, and underscores.
    Other characters are replaced with underscores.

    Args:
        name: The machine name to sanitize.

    Returns:
        Safe machine name.
    """
    return "".join(c if c.isalnum() or c in "-_" else "_" for c in name)


def get_registered_machine_name() -> str | None:
    """Get the registered machine name from config.

    Returns:
        Machine name if registered, None otherwise.
    """
    config = load_config()
    return config.get("machine_name")
