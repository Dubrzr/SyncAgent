"""Command-line interface for SyncAgent.

Provides commands for:
- init: Initialize a new keystore
- unlock: Unlock the keystore with password
- export-key: Export the encryption key
- import-key: Import an encryption key
- register-protocol: Register syncfile:// URL handler
- unregister-protocol: Unregister syncfile:// URL handler
- open-url: Handle a syncfile:// URL
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from syncagent.client.keystore import (
    KeyStoreError,
    create_keystore,
    load_keystore,
)
from syncagent.client.protocol import (
    InvalidURLError,
    RegistrationError,
    SecurityError,
    handle_url,
    is_registered,
    register_protocol,
    unregister_protocol,
)


def get_config_dir() -> Path:
    """Get the configuration directory for SyncAgent.

    Returns:
        Path to ~/.syncagent or equivalent.
    """
    return Path.home() / ".syncagent"


@click.group()
@click.version_option()
def cli() -> None:
    """SyncAgent - Zero-Knowledge E2EE file synchronization."""


@cli.command()
def init() -> None:
    """Initialize a new SyncAgent keystore.

    Creates a new encryption key and stores it securely.
    You will be prompted to set a master password.
    """
    config_dir = get_config_dir()

    # Check if already initialized
    if (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent already initialized.", err=True)
        click.echo(f"Keystore exists at: {config_dir / 'keyfile.json'}", err=True)
        sys.exit(1)

    # Prompt for password with confirmation
    password = click.prompt(
        "Enter master password",
        hide_input=True,
        confirmation_prompt="Confirm master password",
    )

    try:
        keystore = create_keystore(password, config_dir)
        click.echo("SyncAgent initialized successfully!")
        click.echo(f"Key ID: {keystore.key_id}")
        click.echo(f"Config directory: {config_dir}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command()
def unlock() -> None:
    """Unlock the SyncAgent keystore.

    Decrypts and caches the encryption key for use.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        click.echo("Keystore unlocked successfully!")
        click.echo(f"Key ID: {keystore.key_id}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("export-key")
def export_key() -> None:
    """Export the encryption key.

    Outputs the base64-encoded encryption key.
    Use this to transfer your key to another device.

    WARNING: Keep this key secret! Anyone with this key
    can decrypt your files.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        key_b64 = keystore.export_key()
        click.echo("\nEncryption key (keep secret!):")
        click.echo(key_b64)
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@cli.command("import-key")
@click.argument("key")
def import_key(key: str) -> None:
    """Import an encryption key.

    KEY is the base64-encoded encryption key from another device.

    This will replace your current encryption key.
    Make sure both devices use the same key to sync files.
    """
    config_dir = get_config_dir()

    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    password = click.prompt("Enter master password", hide_input=True)

    try:
        keystore = load_keystore(password, config_dir)
        keystore.import_key(key)
        click.echo("Encryption key imported successfully!")
        click.echo(f"New Key ID: {keystore.key_id}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


def get_sync_folder() -> Path:
    """Get the sync folder path.

    Returns:
        Path to the sync folder (configured or default ~/SyncAgent).
    """
    # TODO: Read from config file in get_config_dir()
    return Path.home() / "SyncAgent"


@cli.command("register-protocol")
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


@cli.command("unregister-protocol")
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


@cli.command("open-url")
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


@cli.command("protocol-status")
def protocol_status() -> None:
    """Check if the syncfile:// protocol handler is registered."""
    if is_registered():
        click.echo("Protocol handler: REGISTERED")
    else:
        click.echo("Protocol handler: NOT REGISTERED")
        click.echo("Run 'syncagent register-protocol' to enable syncfile:// links.")


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
