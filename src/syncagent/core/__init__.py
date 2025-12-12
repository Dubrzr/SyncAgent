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
from syncagent.core.config import ServerConfig
from syncagent.core.crypto import (
    compute_file_hash,
    decrypt_chunk,
    derive_key,
    encrypt_chunk,
    generate_salt,
)
from syncagent.core.types import SyncState

__all__ = [
    # Chunking
    "AVG_CHUNK_SIZE",
    "Chunk",
    "MAX_CHUNK_SIZE",
    "MIN_CHUNK_SIZE",
    "chunk_bytes",
    "chunk_file",
    "get_chunk_hash",
    # Config
    "ServerConfig",
    # Crypto
    "compute_file_hash",
    "decrypt_chunk",
    "derive_key",
    "encrypt_chunk",
    "generate_salt",
    # Types
    "SyncState",
]
