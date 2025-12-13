"""Machine registration command for SyncAgent CLI.

Commands:
- register: Register this machine with a server
"""

from __future__ import annotations

import sys

import click

from syncagent.client.cli.config import (
    get_config_dir,
    load_config,
    sanitize_machine_name,
    save_config,
)


@click.command()
@click.option(
    "--server",
    required=True,
    help="Server URL (e.g., http://localhost:8000).",
)
@click.option(
    "--token",
    required=True,
    help="Invitation token from the server admin.",
)
@click.option(
    "--name",
    default=None,
    help="Machine name (default: hostname).",
)
def register(server: str, token: str, name: str | None) -> None:
    """Register this machine with a SyncAgent server.

    Requires an invitation token from the server admin.
    Creates a connection between this machine and the server.
    """
    import platform
    import socket

    import httpx

    config_dir = get_config_dir()

    # Check if initialized
    if not (config_dir / "keyfile.json").exists():
        click.echo("Error: SyncAgent not initialized. Run 'syncagent init' first.", err=True)
        sys.exit(1)

    # Check if already registered
    config = load_config()
    if config.get("server_url") and config.get("auth_token"):
        click.echo("Warning: This machine is already registered.", err=True)
        if not click.confirm("Do you want to re-register with a new server?"):
            sys.exit(0)

    # Determine machine name (sanitized for safe filenames)
    default_name = sanitize_machine_name(socket.gethostname())
    if name:
        machine_name = sanitize_machine_name(name)
        if machine_name != name:
            click.echo(f"Note: Machine name sanitized to '{machine_name}'")
    else:
        machine_name = click.prompt(
            "Machine name (alphanumeric, hyphens, underscores only)",
            default=default_name,
            show_default=True,
        )
        sanitized = sanitize_machine_name(machine_name)
        if sanitized != machine_name:
            click.echo(f"Note: Machine name sanitized to '{sanitized}'")
            machine_name = sanitized

    machine_platform = platform.system().lower()

    click.echo(f"\nRegistering machine '{machine_name}' with server...")

    # Call the registration API
    try:
        response = httpx.post(
            f"{server.rstrip('/')}/api/machines/register",
            json={
                "name": machine_name,
                "platform": machine_platform,
                "invitation_token": token,
            },
            timeout=30.0,
        )

        if response.status_code == 401:
            click.echo("Error: Invalid or expired invitation token.", err=True)
            sys.exit(1)
        elif response.status_code == 409:
            click.echo(f"Error: Machine name '{machine_name}' already exists on server.", err=True)
            click.echo("Use --name to specify a different name.")
            sys.exit(1)
        elif response.status_code != 201:
            detail = response.json().get("detail", "Unknown error")
            click.echo(f"Error: {detail}", err=True)
            sys.exit(1)

        data = response.json()
        auth_token = data["token"]
        machine_info = data["machine"]

        # Save configuration
        config["server_url"] = server.rstrip("/")
        config["auth_token"] = auth_token
        config["machine_name"] = machine_info["name"]
        save_config(config)

        click.echo("\nMachine registered successfully!")
        click.echo(f"Server: {server}")
        click.echo(f"Machine name: {machine_info['name']}")

    except httpx.ConnectError:
        click.echo(f"Error: Could not connect to server at {server}", err=True)
        click.echo("Make sure the server is running and accessible.")
        sys.exit(1)
    except httpx.RequestError as e:
        click.echo(f"Error: Request failed: {e}", err=True)
        sys.exit(1)
