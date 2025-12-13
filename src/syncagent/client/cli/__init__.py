"""Command-line interface for SyncAgent.

This module provides the main CLI entry point and assembles all commands.

Commands:
- init: Initialize a new keystore
- reset: Reset SyncAgent configuration
- unlock: Unlock the keystore with password
- export-key: Export the encryption key
- import-key: Import an encryption key
- register: Register this machine with a server
- sync: Synchronize files with the server
- register-protocol: Register syncfile:// URL handler
- unregister-protocol: Unregister syncfile:// URL handler
- open-url: Handle a syncfile:// URL
- protocol-status: Check protocol registration status
- tray: Start the system tray icon
- server: Server administration commands
"""

from __future__ import annotations

import click

from syncagent.client.cli.config import (
    get_config_dir,
    get_config_file,
    get_registered_machine_name,
    get_sync_folder,
    load_config,
    sanitize_machine_name,
    save_config,
)
from syncagent.client.cli.keystore import (
    export_key,
    import_key,
    init,
    reset,
    unlock,
)
from syncagent.client.cli.protocol import (
    open_url,
    protocol_status,
    register_protocol_cmd,
    unregister_protocol_cmd,
)
from syncagent.client.cli.register import register
from syncagent.client.cli.server import server
from syncagent.client.cli.sync import sync
from syncagent.client.cli.tray import tray


@click.group()
@click.version_option()
def cli() -> None:
    """SyncAgent - Zero-Knowledge E2EE file synchronization."""


# Keystore commands
cli.add_command(init)
cli.add_command(reset)
cli.add_command(unlock)
cli.add_command(export_key)
cli.add_command(import_key)

# Sync commands
cli.add_command(register)
cli.add_command(sync)

# Protocol commands
cli.add_command(register_protocol_cmd)
cli.add_command(unregister_protocol_cmd)
cli.add_command(open_url)
cli.add_command(protocol_status)

# Tray command
cli.add_command(tray)

# Server admin commands
cli.add_command(server)


def main() -> None:
    """Entry point for the CLI."""
    cli()


__all__ = [
    # Main entry points
    "cli",
    "main",
    # Config utilities (for backwards compatibility)
    "get_config_dir",
    "get_config_file",
    "get_registered_machine_name",
    "get_sync_folder",
    "load_config",
    "sanitize_machine_name",
    "save_config",
]
