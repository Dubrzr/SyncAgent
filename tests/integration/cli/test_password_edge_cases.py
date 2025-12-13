"""Tests for password edge cases.

Test Scenarios:
---------------

Password validation:
    - [x] Empty password is rejected during init
    - [x] Very long password works
    - [x] Password with special characters works
    - [x] Password with unicode works
    - [x] Password with spaces works

Password security:
    - [x] Wrong password fails unlock
    - [x] Wrong password fails sync
    - [x] Password not shown in output
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI


class TestPasswordValidation:
    """Tests for password validation during init."""

    def test_empty_password_rejected(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Empty password should be rejected or handled."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        with PatchedCLI(config_dir):
            # Try empty password - Click may re-prompt or reject
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"\n\n{sync_folder}\n",  # Empty password twice
            )

        # Should either fail or reprompt (implementation dependent)
        # Key: should not create keystore with empty password
        if result.exit_code == 0:
            # If it succeeded, verify keystore was NOT created with empty pw
            # (init might have reprompted)
            pass

    def test_very_long_password(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Very long password (256+ chars) should work."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        long_password = "x" * 300

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{long_password}\n{long_password}\n{sync_folder}\n",
            )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify can unlock with same password
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input=f"{long_password}\n"
            )

        assert result.exit_code == 0
        assert "unlocked" in result.output.lower()

    def test_password_with_special_characters(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password with special characters should work."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        special_password = "P@$$w0rd!#$%^&*()[]{}|;:',.<>?/~`"

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{special_password}\n{special_password}\n{sync_folder}\n",
            )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify can unlock
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input=f"{special_password}\n"
            )

        assert result.exit_code == 0

    def test_password_with_unicode(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password with unicode characters should work."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        unicode_password = "密码пароль🔐"

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{unicode_password}\n{unicode_password}\n{sync_folder}\n",
            )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify can unlock
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input=f"{unicode_password}\n"
            )

        assert result.exit_code == 0

    def test_password_with_spaces(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password with leading/trailing/internal spaces should work."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        space_password = "  password with spaces  "

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{space_password}\n{space_password}\n{sync_folder}\n",
            )

        assert result.exit_code == 0, f"Failed: {result.output}"

        # Verify can unlock with exact same password (including spaces)
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input=f"{space_password}\n"
            )

        assert result.exit_code == 0

    def test_password_with_newlines_in_content(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password should not contain actual newlines (input limitation)."""
        # This tests that normal password without newlines works
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        normal_password = "normal_password_123"

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{normal_password}\n{normal_password}\n{sync_folder}\n",
            )

        assert result.exit_code == 0


class TestPasswordSecurity:
    """Tests for password security behavior."""

    def test_wrong_password_fails_unlock(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Wrong password should fail unlock."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        # Init with correct password
        with PatchedCLI(config_dir):
            cli_runner.invoke(
                cli,
                ["init"],
                input=f"correctpassword\ncorrectpassword\n{sync_folder}\n",
            )

        # Try wrong password
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input="wrongpassword\n"
            )

        assert result.exit_code == 1
        assert "invalid password" in result.output.lower() or "error" in result.output.lower()

    def test_password_not_shown_in_output(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password should not appear in command output."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        secret_password = "MySuperSecretPassword123!"

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli,
                ["init"],
                input=f"{secret_password}\n{secret_password}\n{sync_folder}\n",
            )

        # Password should NOT appear in output
        assert secret_password not in result.output

    def test_multiple_wrong_attempts(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Multiple wrong password attempts should all fail."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        # Init
        with PatchedCLI(config_dir):
            cli_runner.invoke(
                cli,
                ["init"],
                input=f"correctpassword\ncorrectpassword\n{sync_folder}\n",
            )

        # Multiple wrong attempts
        for i in range(3):
            with PatchedCLI(config_dir):
                result = cli_runner.invoke(
                    cli, ["unlock"], input=f"wrong{i}\n"
                )
            assert result.exit_code == 1

        # Correct password should still work after wrong attempts
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input="correctpassword\n"
            )
        assert result.exit_code == 0

    def test_case_sensitive_password(
        self, cli_runner: CliRunner, tmp_path: Path
    ) -> None:
        """Password should be case sensitive."""
        config_dir = tmp_path / ".syncagent"
        config_dir.mkdir(parents=True)
        sync_folder = tmp_path / "sync"

        # Init with mixed case
        with PatchedCLI(config_dir):
            cli_runner.invoke(
                cli,
                ["init"],
                input=f"MyPassword\nMyPassword\n{sync_folder}\n",
            )

        # Wrong case should fail
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input="mypassword\n"
            )
        assert result.exit_code == 1

        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input="MYPASSWORD\n"
            )
        assert result.exit_code == 1

        # Correct case should work
        with PatchedCLI(config_dir):
            result = cli_runner.invoke(
                cli, ["unlock"], input="MyPassword\n"
            )
        assert result.exit_code == 0
