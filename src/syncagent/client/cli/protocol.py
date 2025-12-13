"""Protocol handler commands for SyncAgent CLI.

Commands:
- register-protocol: Register the syncfile:// protocol handler
- unregister-protocol: Unregister the syncfile:// protocol handler
- open-url: Open a syncfile:// URL
- protocol-status: Check protocol registration status
"""

from __future__ import annotations

import sys

import click

from syncagent.client.cli.config import get_sync_folder
from syncagent.client.protocol import (
    InvalidURLError,
    RegistrationError,
    SecurityError,
    handle_url,
    is_registered,
    register_protocol,
    unregister_protocol,
)


@click.command("register-protocol")
def register_protocol_cmd() -> None:
    """Register the syncfile:// protocol handler.

    Registers SyncAgent as the handler for syncfile:// URLs
    on your operating system. This allows clicking links in
    the web dashboard to open files locally.
    """
    try:
        if is_registered():
            click.echo("Protocol handler is already registered.")
            return

        register_protocol()
        click.echo("Protocol handler registered successfully!")
        click.echo("You can now open syncfile:// URLs.")
    except RegistrationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command("unregister-protocol")
def unregister_protocol_cmd() -> None:
    """Unregister the syncfile:// protocol handler.

    Removes SyncAgent as the handler for syncfile:// URLs.
    """
    try:
        if not is_registered():
            click.echo("Protocol handler is not registered.")
            return

        unregister_protocol()
        click.echo("Protocol handler unregistered successfully!")
    except RegistrationError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command("open-url")
@click.argument("url")
def open_url(url: str) -> None:
    """Open a syncfile:// URL.

    URL is the syncfile:// URL to open.

    This command is typically called by the operating system
    when clicking a syncfile:// link.
    """
    sync_folder = get_sync_folder()

    if not sync_folder.exists():
        click.echo(f"Error: Sync folder not found: {sync_folder}", err=True)
        sys.exit(1)

    try:
        file_path = handle_url(url, sync_folder)
        click.echo(f"Opened: {file_path}")
    except InvalidURLError as e:
        click.echo(f"Invalid URL: {e}", err=True)
        sys.exit(1)
    except SecurityError as e:
        click.echo(f"Security error: {e}", err=True)
        sys.exit(1)
    except FileNotFoundError as e:
        click.echo(f"File not found: {e}", err=True)
        sys.exit(1)
    except Exception as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command("protocol-status")
def protocol_status() -> None:
    """Check if the syncfile:// protocol handler is registered."""
    if is_registered():
        click.echo("Protocol handler: REGISTERED")
    else:
        click.echo("Protocol handler: NOT REGISTERED")
        click.echo("Run 'syncagent register-protocol' to enable syncfile:// links.")
