"""Core module - Shared crypto, chunking, and models."""

from syncagent.core.chunking import (
    AVG_CHUNK_SIZE,
    MAX_CHUNK_SIZE,
    MIN_CHUNK_SIZE,
    Chunk,
    chunk_bytes,
    chunk_file,
    get_chunk_hash,
)
from syncagent.core.crypto import (
    decrypt_chunk,
    derive_key,
    encrypt_chunk,
    generate_salt,
)

__all__ = [
    # Chunking
    "AVG_CHUNK_SIZE",
    "Chunk",
    "MAX_CHUNK_SIZE",
    "MIN_CHUNK_SIZE",
    "chunk_bytes",
    "chunk_file",
    "get_chunk_hash",
    # Crypto
    "decrypt_chunk",
    "derive_key",
    "encrypt_chunk",
    "generate_salt",
]
