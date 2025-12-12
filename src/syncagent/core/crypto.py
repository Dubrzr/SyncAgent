"""Cryptographic functions for SyncAgent.

This module provides:
- Key derivation using Argon2id
- Authenticated encryption using AES-256-GCM
- File hashing with SHA-256
"""

import hashlib
import os
from pathlib import Path

from argon2.low_level import Type, hash_secret_raw
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

# Argon2id parameters (OWASP recommendations for password hashing)
ARGON2_TIME_COST = 3
ARGON2_MEMORY_COST = 65536  # 64 MiB
ARGON2_PARALLELISM = 4
ARGON2_HASH_LEN = 32  # 256 bits

# AES-GCM constants
NONCE_SIZE = 12  # 96 bits (recommended for AES-GCM)
SALT_SIZE = 16  # 128 bits


def generate_salt() -> bytes:
    """Generate a cryptographically secure random salt.

    Returns:
        16 bytes of random data for use as salt in key derivation.
    """
    return os.urandom(SALT_SIZE)


def derive_key(password: str, salt: bytes) -> bytes:
    """Derive a 256-bit encryption key from a password using Argon2id.

    Args:
        password: The user's master password.
        salt: A 16-byte random salt (use generate_salt()).

    Returns:
        32 bytes (256 bits) derived key suitable for AES-256.
    """
    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME_COST,
        memory_cost=ARGON2_MEMORY_COST,
        parallelism=ARGON2_PARALLELISM,
        hash_len=ARGON2_HASH_LEN,
        type=Type.ID,
    )


def encrypt_chunk(data: bytes, key: bytes) -> bytes:
    """Encrypt data using AES-256-GCM with a random nonce.

    Args:
        data: Plaintext data to encrypt.
        key: 32-byte encryption key.

    Returns:
        Encrypted data in format: nonce (12 bytes) || ciphertext || auth_tag (16 bytes)
    """
    nonce = os.urandom(NONCE_SIZE)
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext


def decrypt_chunk(encrypted: bytes, key: bytes) -> bytes:
    """Decrypt data encrypted with encrypt_chunk.

    Args:
        encrypted: Data in format: nonce (12 bytes) || ciphertext || auth_tag (16 bytes)
        key: 32-byte encryption key.

    Returns:
        Decrypted plaintext data.

    Raises:
        cryptography.exceptions.InvalidTag: If authentication fails (wrong key or tampered data).
    """
    nonce = encrypted[:NONCE_SIZE]
    ciphertext = encrypted[NONCE_SIZE:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)


def compute_file_hash(path: Path) -> str:
    """Compute SHA-256 hash of a file.

    Reads the file in chunks to handle large files efficiently.

    Args:
        path: Path to the file to hash.

    Returns:
        Hexadecimal SHA-256 hash string.
    """
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(8192), b""):
            hasher.update(block)
    return hasher.hexdigest()
