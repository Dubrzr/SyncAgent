"""Keystore management commands for SyncAgent CLI.

Specs:
- docs/cli/init.md
- docs/cli/reset.md
- docs/cli/unlock.md

Commands:
- init: Initialize a new keystore
- reset: Reset SyncAgent configuration
- unlock: Unlock the keystore
- export-key: Export the encryption key
- import-key: Import an encryption key
"""

from __future__ import annotations

import sys
from pathlib import Path

import click

from syncagent.client.cli.config import (
    get_config_dir,
    load_config,
    save_config,
)
from syncagent.client.keystore import (
    KeyStoreError,
    create_keystore,
    load_keystore,
)


@click.command()
def init() -> None:
    """Initialize a new SyncAgent keystore.

    Creates a new encryption key and stores it securely.
    You will be prompted to create a master password and choose a sync folder.
    """
    config_dir = get_config_dir()

    # Check if already initialized
    if (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent already initialized.", err=True)
        click.echo(f"Keystore exists at: {config_dir / 'keyfile.json'}", err=True)
        click.echo("\nTo start over, run:")
        click.echo("  syncagent reset")
        sys.exit(1)

    click.echo("Welcome to SyncAgent!")
    click.echo("This wizard will help you set up secure file synchronization.\n")

    # Prompt for password with confirmation
    click.echo("First, create a master password to protect your encryption key.")
    click.echo("Choose a strong password - you'll need it to unlock SyncAgent.\n")

    password = click.prompt(
        "Create master password",
        hide_input=True,
        confirmation_prompt="Confirm master password",
    )

    # Prompt for sync folder
    default_sync_folder = Path.home() / "SyncAgent"
    click.echo("\nWhere do you want to sync files?")
    sync_folder_input = click.prompt(
        "Sync folder",
        default=str(default_sync_folder),
        show_default=True,
    )
    sync_path = Path(sync_folder_input).expanduser().resolve()

    try:
        keystore = create_keystore(password, config_dir)

        # Create sync folder if it doesn't exist
        if not sync_path.exists():
            sync_path.mkdir(parents=True)
            click.echo(f"\nCreated sync folder: {sync_path}")

        # Save sync folder to config
        config = load_config()
        config["sync_folder"] = str(sync_path)
        save_config(config)

        click.echo("\nSyncAgent initialized successfully!")
        click.echo(f"Key ID: {keystore.key_id}")
        click.echo(f"Config directory: {config_dir}")
        click.echo(f"Sync folder: {sync_path}")

        # Next steps guidance
        click.echo("\n" + "=" * 50)
        click.echo("NEXT STEPS:")
        click.echo("=" * 50)
        click.echo("\n1. Start the server (if not already running):")
        click.echo("   uvicorn syncagent.server.app:app --host 0.0.0.0 --port 8000")
        click.echo("\n2. Open http://localhost:8000 and create an admin account")
        click.echo("\n3. Go to 'Invitations' and create a token for this machine")
        click.echo("\n4. Register this machine with the server:")
        click.echo(
            "   syncagent register --server http://localhost:8000 --token <invitation-token>"
        )

    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)


@click.command()
@click.option(
    "--force",
    is_flag=True,
    help="Skip confirmation prompt.",
)
def reset(force: bool) -> None:
    """Reset SyncAgent configuration.

    Deletes the config directory (~/.syncagent) to allow re-initialization.
    This will NOT delete your sync folder or synced files.

    WARNING: This will delete your encryption key! Make sure you have
    exported it first if you need to recover your files.
    """
    import shutil

    config_dir = get_config_dir()

    if not config_dir.exists():
        click.echo("Nothing to reset. SyncAgent is not initialized.")
        return

    if not force:
        click.echo("WARNING: This will delete your SyncAgent configuration, including:")
        click.echo("  - Encryption key (keyfile.json)")
        click.echo("  - Server registration (config.json)")
        click.echo(f"\nConfig directory: {config_dir}")
        click.echo("\nYour sync folder and files will NOT be deleted.")
        click.echo("\nMake sure you have exported your encryption key if needed:")
        click.echo("  syncagent export-key\n")

        if not click.confirm("Are you sure you want to reset?"):
            click.echo("Aborted.")
            return

    try:
        shutil.rmtree(config_dir)
        click.echo("SyncAgent configuration has been reset.")
        click.echo("Run 'syncagent init' to set up again.")
    except OSError as e:
        click.echo(f"Error deleting config directory: {e}", err=True)
        sys.exit(1)


@click.command()
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


@click.command("export-key")
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


@click.command("import-key")
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
        keystore.import_key(key, password)
        click.echo("Encryption key imported successfully!")
        click.echo(f"New Key ID: {keystore.key_id}")
    except KeyStoreError as e:
        click.echo(f"Error: {e}", err=True)
        sys.exit(1)
