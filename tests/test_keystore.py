"""Tests for keystore module - Secure key storage and management."""

import base64
import json
from pathlib import Path
from unittest.mock import patch

import pytest

from syncagent.client.keystore import (
    KeyStoreError,
    create_keystore,
    load_keystore,
)


class TestKeyStoreCreation:
    """Tests for creating a new keystore."""

    def test_create_keystore_generates_encryption_key(self, tmp_path: Path) -> None:
        """Creating a keystore should generate a random encryption key."""
        keystore = create_keystore("master_password", tmp_path)
        assert keystore.encryption_key is not None
        assert len(keystore.encryption_key) == 32

    def test_create_keystore_creates_keyfile(self, tmp_path: Path) -> None:
        """Creating a keystore should create a keyfile.json."""
        create_keystore("master_password", tmp_path)
        keyfile = tmp_path / "keyfile.json"
        assert keyfile.exists()

    def test_create_keystore_keyfile_has_required_fields(self, tmp_path: Path) -> None:
        """Keyfile should have salt, encrypted_master_key, key_id, created_at."""
        create_keystore("master_password", tmp_path)
        keyfile = tmp_path / "keyfile.json"
        data = json.loads(keyfile.read_text())
        assert "salt" in data
        assert "encrypted_master_key" in data
        assert "key_id" in data
        assert "created_at" in data

    def test_create_keystore_different_passwords_different_keys(
        self, tmp_path: Path
    ) -> None:
        """Different passwords should produce different encryption keys."""
        ks1 = create_keystore("password1", tmp_path / "ks1")
        ks2 = create_keystore("password2", tmp_path / "ks2")
        assert ks1.encryption_key != ks2.encryption_key

    def test_create_keystore_fails_if_exists(self, tmp_path: Path) -> None:
        """Creating a keystore should fail if keyfile already exists."""
        create_keystore("master_password", tmp_path)
        with pytest.raises(KeyStoreError, match="already exists"):
            create_keystore("master_password", tmp_path)


class TestKeyStoreLoading:
    """Tests for loading an existing keystore."""

    def test_load_keystore_recovers_encryption_key(self, tmp_path: Path) -> None:
        """Loading a keystore should recover the same encryption key."""
        original = create_keystore("master_password", tmp_path)
        loaded = load_keystore("master_password", tmp_path)
        assert loaded.encryption_key == original.encryption_key

    def test_load_keystore_wrong_password_fails(self, tmp_path: Path) -> None:
        """Loading with wrong password should fail."""
        create_keystore("correct_password", tmp_path)
        with pytest.raises(KeyStoreError, match="Invalid password"):
            load_keystore("wrong_password", tmp_path)

    def test_load_keystore_missing_keyfile_fails(self, tmp_path: Path) -> None:
        """Loading from non-existent keyfile should fail."""
        with pytest.raises(KeyStoreError, match="not found"):
            load_keystore("password", tmp_path)

    def test_load_keystore_corrupted_keyfile_fails(self, tmp_path: Path) -> None:
        """Loading from corrupted keyfile should fail."""
        keyfile = tmp_path / "keyfile.json"
        keyfile.write_text("not valid json")
        with pytest.raises(KeyStoreError):
            load_keystore("password", tmp_path)


class TestKeyStoreWithKeyring:
    """Tests for keyring integration (OS credential storage)."""

    def test_unlock_stores_key_in_keyring(self, tmp_path: Path) -> None:
        """Unlocking should store the encryption key in keyring."""
        with patch("syncagent.client.keystore.keyring") as mock_keyring:
            keystore = create_keystore("master_password", tmp_path)
            mock_keyring.reset_mock()  # Clear calls from create
            keystore.unlock("master_password")
            mock_keyring.set_password.assert_called_once()

    def test_get_key_from_keyring_when_cached(self, tmp_path: Path) -> None:
        """Should retrieve key from keyring if available."""
        # First create without mock to get real key
        keystore = create_keystore("master_password", tmp_path)
        real_key_b64 = base64.b64encode(keystore.encryption_key).decode()

        # Now test keyring retrieval
        with patch("syncagent.client.keystore.keyring") as mock_keyring:
            mock_keyring.get_password.return_value = real_key_b64
            # Clear the in-memory key to simulate restart
            keystore._encryption_key = None
            # Should get from keyring
            key = keystore.encryption_key
            mock_keyring.get_password.assert_called()
            assert len(key) == 32

    def test_keyring_fallback_when_unavailable(self, tmp_path: Path) -> None:
        """Should work without keyring (fallback to password entry)."""
        with patch("syncagent.client.keystore.keyring") as mock_keyring:
            mock_keyring.set_password.side_effect = Exception("No keyring")
            mock_keyring.get_password.return_value = None
            keystore = create_keystore("master_password", tmp_path)
            # Should still work - key is in memory
            assert len(keystore.encryption_key) == 32


class TestKeyExportImport:
    """Tests for key export and import functionality."""

    def test_export_key_returns_base64(self, tmp_path: Path) -> None:
        """Export should return base64-encoded key."""
        keystore = create_keystore("master_password", tmp_path)
        exported = keystore.export_key()
        assert isinstance(exported, str)
        # Should be valid base64
        import base64

        decoded = base64.b64decode(exported)
        assert len(decoded) == 32

    def test_import_key_restores_same_key(self, tmp_path: Path) -> None:
        """Import should restore the same encryption key."""
        ks1 = create_keystore("password1", tmp_path / "ks1")
        exported = ks1.export_key()

        # Create new keystore and import key
        ks2 = create_keystore("password2", tmp_path / "ks2")
        ks2.import_key(exported, "password2")

        assert ks2.encryption_key == ks1.encryption_key

    def test_import_key_updates_keyfile(self, tmp_path: Path) -> None:
        """Import should update the keyfile with new encrypted key."""
        ks1 = create_keystore("password1", tmp_path / "ks1")
        exported = ks1.export_key()

        ks2 = create_keystore("password2", tmp_path / "ks2")
        original_keyfile = (tmp_path / "ks2" / "keyfile.json").read_text()
        ks2.import_key(exported, "password2")
        updated_keyfile = (tmp_path / "ks2" / "keyfile.json").read_text()

        assert original_keyfile != updated_keyfile

    def test_import_invalid_key_fails(self, tmp_path: Path) -> None:
        """Import should fail with invalid base64."""
        keystore = create_keystore("password", tmp_path)
        with pytest.raises(KeyStoreError, match="Invalid key"):
            keystore.import_key("not-valid-base64!!!", "password")

    def test_import_wrong_length_key_fails(self, tmp_path: Path) -> None:
        """Import should fail if key is not 32 bytes."""
        import base64

        keystore = create_keystore("password", tmp_path)
        short_key = base64.b64encode(b"short").decode()
        with pytest.raises(KeyStoreError, match="must be 32 bytes"):
            keystore.import_key(short_key, "password")


class TestKeyStoreKeyId:
    """Tests for key_id functionality."""

    def test_key_id_is_uuid(self, tmp_path: Path) -> None:
        """Key ID should be a valid UUID."""
        import uuid

        keystore = create_keystore("password", tmp_path)
        # Should not raise
        uuid.UUID(keystore.key_id)

    def test_key_id_persists_across_loads(self, tmp_path: Path) -> None:
        """Key ID should remain the same after reloading."""
        original = create_keystore("password", tmp_path)
        loaded = load_keystore("password", tmp_path)
        assert loaded.key_id == original.key_id

    def test_import_key_changes_key_id(self, tmp_path: Path) -> None:
        """Importing a new key should change the key_id."""
        import base64
        import os

        keystore = create_keystore("password", tmp_path)
        original_id = keystore.key_id

        new_key = base64.b64encode(os.urandom(32)).decode()
        keystore.import_key(new_key, "password")

        assert keystore.key_id != original_id
