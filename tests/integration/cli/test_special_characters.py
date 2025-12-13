"""Tests for special characters in file names and content.

Test Scenarios:
---------------

Unicode file names:
    - [x] Chinese characters in filename
    - [x] Japanese characters in filename
    - [x] Arabic characters in filename
    - [x] Cyrillic characters in filename
    - [x] Emoji in filename
    - [x] Mixed scripts in filename

Special characters:
    - [x] Spaces in filename
    - [x] Parentheses in filename
    - [x] Brackets in filename
    - [x] Dashes and underscores
    - [x] Multiple dots in filename

Unicode content:
    - [x] File with unicode content syncs correctly
    - [x] Mixed language content
"""

from __future__ import annotations

from pathlib import Path

from click.testing import CliRunner

from syncagent.client.cli import cli
from tests.integration.cli.fixtures import PatchedCLI, init_client, register_client
from tests.integration.conftest import TestServer


def setup_client(
    cli_runner: CliRunner,
    tmp_path: Path,
    test_server: TestServer,
    name: str,
    import_key_from: Path | None = None,
) -> tuple[Path, Path]:
    """Setup a client for testing."""
    config_dir = tmp_path / name / ".syncagent"
    config_dir.mkdir(parents=True, exist_ok=True)
    sync_folder = tmp_path / name / "sync"
    sync_folder.mkdir(parents=True, exist_ok=True)

    init_client(cli_runner, config_dir, sync_folder)

    if import_key_from:
        with PatchedCLI(import_key_from):
            result = cli_runner.invoke(cli, ["export-key"], input="testpassword\n")
            lines = [line.strip() for line in result.output.split("\n") if line.strip()]
            exported_key = lines[-1]
        with PatchedCLI(config_dir):
            cli_runner.invoke(cli, ["import-key", exported_key], input="testpassword\n")

    token = test_server.create_invitation()
    register_client(cli_runner, config_dir, test_server.url, token, name)

    return config_dir, sync_folder


def do_sync(cli_runner: CliRunner, config_dir: Path) -> str:
    """Run sync and return output."""
    with PatchedCLI(config_dir):
        result = cli_runner.invoke(cli, ["sync"], input="testpassword\n")
        if result.exit_code != 0:
            raise RuntimeError(f"sync failed: {result.output}")
        return result.output


class TestUnicodeFilenames:
    """Tests for unicode characters in filenames."""

    def test_chinese_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Chinese characters in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with Chinese name
        (sync_a / "文档.txt").write_text("Chinese filename")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "文档.txt").read_text() == "Chinese filename"

    def test_japanese_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Japanese characters in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with Japanese name (hiragana + kanji)
        (sync_a / "ファイル名.txt").write_text("Japanese filename")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "ファイル名.txt").read_text() == "Japanese filename"

    def test_arabic_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Arabic characters in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with Arabic name
        (sync_a / "ملف.txt").write_text("Arabic filename")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "ملف.txt").read_text() == "Arabic filename"

    def test_cyrillic_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Cyrillic characters in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with Russian name
        (sync_a / "документ.txt").write_text("Cyrillic filename")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "документ.txt").read_text() == "Cyrillic filename"

    def test_emoji_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Emoji in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with emoji name
        (sync_a / "🎉party🎊.txt").write_text("Emoji filename")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "🎉party🎊.txt").read_text() == "Emoji filename"

    def test_mixed_scripts_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Mixed scripts in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        # Create file with mixed scripts
        (sync_a / "Hello世界Привет.txt").write_text("Mixed scripts")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "Hello世界Привет.txt").read_text() == "Mixed scripts"


class TestSpecialCharactersInFilename:
    """Tests for special ASCII characters in filenames."""

    def test_spaces_in_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Spaces in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        (sync_a / "file with spaces.txt").write_text("Content")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "file with spaces.txt").read_text() == "Content"

    def test_parentheses_in_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Parentheses in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        (sync_a / "file (copy).txt").write_text("Content")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "file (copy).txt").read_text() == "Content"

    def test_brackets_in_filename(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Brackets in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        (sync_a / "file[1].txt").write_text("Content")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "file[1].txt").read_text() == "Content"

    def test_dashes_underscores(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Dashes and underscores should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        (sync_a / "file-name_with-mixed_chars.txt").write_text("Content")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "file-name_with-mixed_chars.txt").read_text() == "Content"

    def test_multiple_dots(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Multiple dots in filename should sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        (sync_a / "file.backup.2024.01.15.txt").write_text("Content")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "file.backup.2024.01.15.txt").read_text() == "Content"


class TestUnicodeContent:
    """Tests for unicode content in files."""

    def test_unicode_content_preserved(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Unicode content should be preserved during sync."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        content = "Hello 世界! Привет мир! مرحبا بالعالم! 🎉🚀"
        (sync_a / "unicode.txt").write_text(content, encoding="utf-8")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "unicode.txt").read_text(encoding="utf-8") == content

    def test_mixed_language_content(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Mixed language content should sync correctly."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        content = """English: Hello World
中文: 你好世界
日本語: こんにちは世界
한국어: 안녕하세요 세계
العربية: مرحبا بالعالم
Русский: Привет мир
"""
        (sync_a / "multilang.txt").write_text(content, encoding="utf-8")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "multilang.txt").read_text(encoding="utf-8") == content

    def test_diacritics_preserved(
        self,
        cli_runner: CliRunner,
        tmp_path: Path,
        test_server: TestServer,
    ) -> None:
        """Diacritics should be preserved."""
        config_a, sync_a = setup_client(cli_runner, tmp_path, test_server, "client-a")
        config_b, sync_b = setup_client(cli_runner, tmp_path, test_server, "client-b", import_key_from=config_a)

        content = "Café résumé naïve piñata über"
        (sync_a / "diacritics.txt").write_text(content, encoding="utf-8")
        do_sync(cli_runner, config_a)
        do_sync(cli_runner, config_b)

        assert (sync_b / "diacritics.txt").read_text(encoding="utf-8") == content
