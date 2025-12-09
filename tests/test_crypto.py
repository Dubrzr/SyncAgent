"""Tests for crypto module - Key derivation and encryption."""


import os

import pytest
from cryptography.exceptions import InvalidTag

from syncagent.core import (
    decrypt_chunk,
    derive_key,
    encrypt_chunk,
    generate_salt,
)


class TestKeyDerivation:
    """Tests for Argon2id key derivation."""

    def test_derive_key_returns_32_bytes(self) -> None:
        """Key derivation should return exactly 32 bytes (256 bits)."""
        salt = generate_salt()
        key = derive_key("test_password", salt)
        assert len(key) == 32

    def test_derive_key_deterministic(self) -> None:
        """Same password and salt should produce same key."""
        salt = generate_salt()
        key1 = derive_key("test_password", salt)
        key2 = derive_key("test_password", salt)
        assert key1 == key2

    def test_derive_key_different_passwords(self) -> None:
        """Different passwords should produce different keys."""
        salt = generate_salt()
        key1 = derive_key("password1", salt)
        key2 = derive_key("password2", salt)
        assert key1 != key2

    def test_derive_key_different_salts(self) -> None:
        """Different salts should produce different keys."""
        salt1 = generate_salt()
        salt2 = generate_salt()
        key1 = derive_key("test_password", salt1)
        key2 = derive_key("test_password", salt2)
        assert key1 != key2

    def test_derive_key_empty_password(self) -> None:
        """Empty password should still work (user's choice)."""
        salt = generate_salt()
        key = derive_key("", salt)
        assert len(key) == 32

    def test_derive_key_unicode_password(self) -> None:
        """Unicode passwords should work correctly."""
        salt = generate_salt()
        key = derive_key("motdepässé日本語", salt)
        assert len(key) == 32

    def test_derive_key_long_password(self) -> None:
        """Long passwords should work correctly."""
        salt = generate_salt()
        long_password = "a" * 10000
        key = derive_key(long_password, salt)
        assert len(key) == 32

    def test_generate_salt_returns_16_bytes(self) -> None:
        """Salt generation should return 16 bytes."""
        salt = generate_salt()
        assert len(salt) == 16

    def test_generate_salt_unique(self) -> None:
        """Each salt generation should be unique."""
        salts = [generate_salt() for _ in range(100)]
        assert len(set(salts)) == 100


class TestEncryption:
    """Tests for AES-256-GCM encryption/decryption."""

    @pytest.fixture
    def key(self) -> bytes:
        """Generate a valid 32-byte key for testing."""
        return os.urandom(32)

    def test_encrypt_decrypt_roundtrip(self, key: bytes) -> None:
        """Encrypted data should decrypt back to original."""
        plaintext = b"Hello, World!"
        encrypted = encrypt_chunk(plaintext, key)
        decrypted = decrypt_chunk(encrypted, key)
        assert decrypted == plaintext

    def test_encrypt_produces_different_output(self, key: bytes) -> None:
        """Same plaintext encrypted twice should produce different ciphertext (random nonce)."""
        plaintext = b"Hello, World!"
        encrypted1 = encrypt_chunk(plaintext, key)
        encrypted2 = encrypt_chunk(plaintext, key)
        assert encrypted1 != encrypted2

    def test_encrypted_longer_than_plaintext(self, key: bytes) -> None:
        """Encrypted data should be longer (nonce + auth tag)."""
        plaintext = b"Hello, World!"
        encrypted = encrypt_chunk(plaintext, key)
        # 12 bytes nonce + 16 bytes auth tag = 28 bytes overhead
        assert len(encrypted) == len(plaintext) + 12 + 16

    def test_decrypt_with_wrong_key_fails(self, key: bytes) -> None:
        """Decryption with wrong key should raise an error."""
        plaintext = b"Hello, World!"
        encrypted = encrypt_chunk(plaintext, key)
        wrong_key = os.urandom(32)
        with pytest.raises(InvalidTag):
            decrypt_chunk(encrypted, wrong_key)

    def test_decrypt_tampered_data_fails(self, key: bytes) -> None:
        """Decryption of tampered data should raise an error."""
        plaintext = b"Hello, World!"
        encrypted = bytearray(encrypt_chunk(plaintext, key))
        # Tamper with ciphertext (not nonce)
        encrypted[15] ^= 0xFF
        with pytest.raises(InvalidTag):
            decrypt_chunk(bytes(encrypted), key)

    def test_encrypt_empty_data(self, key: bytes) -> None:
        """Empty data should encrypt/decrypt correctly."""
        plaintext = b""
        encrypted = encrypt_chunk(plaintext, key)
        decrypted = decrypt_chunk(encrypted, key)
        assert decrypted == plaintext

    def test_encrypt_large_data(self, key: bytes) -> None:
        """Large data (8MB) should encrypt/decrypt correctly."""
        plaintext = os.urandom(8 * 1024 * 1024)  # 8MB
        encrypted = encrypt_chunk(plaintext, key)
        decrypted = decrypt_chunk(encrypted, key)
        assert decrypted == plaintext

    def test_encrypt_binary_data(self, key: bytes) -> None:
        """Binary data with all byte values should work."""
        plaintext = bytes(range(256)) * 100
        encrypted = encrypt_chunk(plaintext, key)
        decrypted = decrypt_chunk(encrypted, key)
        assert decrypted == plaintext
