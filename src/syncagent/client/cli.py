"""Command-line interface for SyncAgent.

Provides commands for:
- init: Initialize a new keystore
- unlock: Unlock the keystore with password
- export-key: Export the encryption key
- import-key: Import an encryption key
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


def main() -> None:
    """Entry point for the CLI."""
    cli()


if __name__ == "__main__":
    main()
