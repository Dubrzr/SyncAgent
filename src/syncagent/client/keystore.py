"""Secure key storage and management for SyncAgent.

This module provides:
- Key generation and derivation
- Encrypted storage of the master key
- OS keyring integration for caching
- Key export/import for multi-device setup
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

import keyring

from syncagent.core.crypto import decrypt_chunk, derive_key, encrypt_chunk, generate_salt

KEYFILE_NAME = "keyfile.json"
KEYRING_SERVICE = "syncagent"


class KeyStoreError(Exception):
    """Exception raised for keystore-related errors."""


class KeyStore:
    """Manages encryption keys with secure storage.

    The keystore uses a two-key system:
    - master_key: derived from user password using Argon2id
    - encryption_key: random 256-bit key used for file encryption

    The encryption_key is encrypted with master_key and stored in keyfile.json.
    """

    def __init__(
        self,
        config_dir: Path,
        salt: bytes,
        encrypted_master_key: bytes,
        key_id: str,
        created_at: str,
        encryption_key: bytes | None = None,
    ) -> None:
        """Initialize keystore (use create_keystore or load_keystore instead)."""
        self._config_dir = config_dir
        self._salt = salt
        self._encrypted_master_key = encrypted_master_key
        self._key_id = key_id
        self._created_at = created_at
        self._encryption_key = encryption_key

    @property
    def encryption_key(self) -> bytes:
        """Get the encryption key (must be unlocked first)."""
        if self._encryption_key is None:
            # Try to get from keyring
            cached = keyring.get_password(KEYRING_SERVICE, self._key_id)
            if cached:
                self._encryption_key = base64.b64decode(cached)
            else:
                raise KeyStoreError("Keystore is locked. Call unlock() first.")
        return self._encryption_key

    @property
    def key_id(self) -> str:
        """Get the unique key identifier."""
        return self._key_id

    def unlock(self, password: str) -> None:
        """Unlock the keystore with the master password.

        Args:
            password: The master password.

        Raises:
            KeyStoreError: If the password is incorrect.
        """
        master_key = derive_key(password, self._salt)
        try:
            self._encryption_key = decrypt_chunk(self._encrypted_master_key, master_key)
        except Exception as e:
            raise KeyStoreError("Invalid password or corrupted keyfile") from e

        # Cache in keyring (silently ignore if unavailable)
        with contextlib.suppress(Exception):
            keyring.set_password(
                KEYRING_SERVICE,
                self._key_id,
                base64.b64encode(self._encryption_key).decode(),
            )

    def export_key(self) -> str:
        """Export the encryption key as base64.

        Returns:
            Base64-encoded encryption key.
        """
        return base64.b64encode(self.encryption_key).decode()

    def import_key(self, key_b64: str, password: str) -> None:
        """Import an encryption key from base64.

        Args:
            key_b64: Base64-encoded encryption key.
            password: Master password to re-encrypt the new key.

        Raises:
            KeyStoreError: If the key is invalid.
        """
        try:
            key = base64.b64decode(key_b64)
        except Exception as e:
            raise KeyStoreError("Invalid key format: not valid base64") from e

        if len(key) != 32:
            raise KeyStoreError(f"Invalid key: must be 32 bytes, got {len(key)}")

        # Generate new salt and re-encrypt the key with new master key
        new_salt = generate_salt()
        master_key = derive_key(password, new_salt)
        encrypted_key = encrypt_chunk(key, master_key)

        # Update keystore state
        self._encryption_key = key
        self._salt = new_salt
        self._encrypted_master_key = encrypted_key
        self._key_id = str(uuid.uuid4())

        # Save the updated keyfile
        self._save_keyfile()

        # Update keyring cache
        with contextlib.suppress(Exception):
            keyring.set_password(
                KEYRING_SERVICE,
                self._key_id,
                base64.b64encode(key).decode(),
            )

    def _save_keyfile(self) -> None:
        """Save the keyfile with current state."""
        # We need to re-encrypt the key, but we don't have the password
        # This is called after import_key, so we have the key in memory
        # We'll need to regenerate salt and encrypted_master_key
        # For this to work properly, import_key should require password
        # For now, let's use a workaround: store a marker that key was imported
        keyfile = self._config_dir / KEYFILE_NAME
        data = {
            "salt": base64.b64encode(self._salt).decode(),
            "encrypted_master_key": base64.b64encode(self._encrypted_master_key).decode(),
            "key_id": self._key_id,
            "created_at": self._created_at,
        }
        keyfile.write_text(json.dumps(data, indent=2))


def create_keystore(password: str, config_dir: Path) -> KeyStore:
    """Create a new keystore with a random encryption key.

    Args:
        password: Master password for the keystore.
        config_dir: Directory to store the keyfile.

    Returns:
        Unlocked KeyStore instance.

    Raises:
        KeyStoreError: If keystore already exists.
    """
    config_dir = Path(config_dir)
    config_dir.mkdir(parents=True, exist_ok=True)

    keyfile = config_dir / KEYFILE_NAME
    if keyfile.exists():
        raise KeyStoreError(f"Keystore already exists at {keyfile}")

    # Generate random encryption key
    encryption_key = os.urandom(32)

    # Derive master key from password
    salt = generate_salt()
    master_key = derive_key(password, salt)

    # Encrypt the encryption key with master key
    encrypted_master_key = encrypt_chunk(encryption_key, master_key)

    # Generate unique key ID
    key_id = str(uuid.uuid4())
    created_at = datetime.now(UTC).isoformat()

    # Save keyfile
    data = {
        "salt": base64.b64encode(salt).decode(),
        "encrypted_master_key": base64.b64encode(encrypted_master_key).decode(),
        "key_id": key_id,
        "created_at": created_at,
    }
    keyfile.write_text(json.dumps(data, indent=2))

    # Create and return unlocked keystore
    keystore = KeyStore(
        config_dir=config_dir,
        salt=salt,
        encrypted_master_key=encrypted_master_key,
        key_id=key_id,
        created_at=created_at,
        encryption_key=encryption_key,
    )

    # Cache in keyring
    with contextlib.suppress(Exception):
        keyring.set_password(
            KEYRING_SERVICE,
            key_id,
            base64.b64encode(encryption_key).decode(),
        )

    return keystore


def load_keystore(password: str, config_dir: Path) -> KeyStore:
    """Load an existing keystore.

    Args:
        password: Master password for the keystore.
        config_dir: Directory containing the keyfile.

    Returns:
        Unlocked KeyStore instance.

    Raises:
        KeyStoreError: If keystore not found or password is wrong.
    """
    config_dir = Path(config_dir)
    keyfile = config_dir / KEYFILE_NAME

    if not keyfile.exists():
        raise KeyStoreError(f"Keystore not found at {keyfile}")

    try:
        data = json.loads(keyfile.read_text())
    except json.JSONDecodeError as e:
        raise KeyStoreError(f"Corrupted keyfile: {e}") from e

    try:
        salt = base64.b64decode(data["salt"])
        encrypted_master_key = base64.b64decode(data["encrypted_master_key"])
        key_id = data["key_id"]
        created_at = data["created_at"]
    except (KeyError, ValueError) as e:
        raise KeyStoreError(f"Invalid keyfile format: {e}") from e

    # Derive master key and decrypt encryption key
    master_key = derive_key(password, salt)
    try:
        encryption_key = decrypt_chunk(encrypted_master_key, master_key)
    except Exception as e:
        raise KeyStoreError("Invalid password or corrupted keyfile") from e

    keystore = KeyStore(
        config_dir=config_dir,
        salt=salt,
        encrypted_master_key=encrypted_master_key,
        key_id=key_id,
        created_at=created_at,
        encryption_key=encryption_key,
    )

    # Cache in keyring
    with contextlib.suppress(Exception):
        keyring.set_password(
            KEYRING_SERVICE,
            key_id,
            base64.b64encode(encryption_key).decode(),
        )

    return keystore
