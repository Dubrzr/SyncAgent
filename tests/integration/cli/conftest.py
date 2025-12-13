"""Pytest configuration for CLI integration tests.

Imports fixtures from parent conftest (test_server) and local fixtures.
"""

from __future__ import annotations

# Re-export local CLI fixtures
from tests.integration.cli.fixtures import (
    PatchedCLI,
    cli_runner,
    init_client,
    patch_config_dir,
    register_client,
    sync_client,
    test_config_dir,
    test_sync_folder,
)

# Re-export fixtures from parent conftest
from tests.integration.conftest import (
    client_a,
    client_b,
    client_factory,
    encryption_key,
    test_server,
)

__all__ = [
    # Server fixtures
    "test_server",
    "encryption_key",
    "client_factory",
    "client_a",
    "client_b",
    # CLI fixtures
    "cli_runner",
    "test_config_dir",
    "test_sync_folder",
    "patch_config_dir",
    "PatchedCLI",
    "init_client",
    "register_client",
    "sync_client",
]
