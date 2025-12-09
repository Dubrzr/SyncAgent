# SyncAgent

[![CI](https://github.com/Dubrzr/file-sync-ssh/actions/workflows/ci.yml/badge.svg)](https://github.com/Dubrzr/file-sync-ssh/actions/workflows/ci.yml)
[![codecov](https://codecov.io/gh/Dubrzr/file-sync-ssh/graph/badge.svg?token=NWSBTNWZEB)](https://codecov.io/gh/Dubrzr/file-sync-ssh)
[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

Zero-Knowledge End-to-End Encrypted (E2EE) file synchronization system.

## Features

- **Zero-Knowledge E2EE**: All encryption happens client-side. The server never sees your data.
- **Cross-Platform**: Works on Windows, macOS, and Linux.
- **Content-Defined Chunking**: Efficient sync with deduplication using FastCDC.
- **Conflict Detection**: Automatic conflict detection with version tracking.
- **Web Dashboard**: Modern Apple-like UI for file browsing and management.
- **S3-Compatible Storage**: Store encrypted chunks on any S3-compatible backend.

## Architecture

```
┌─────────────┐     HTTPS/WSS      ┌─────────────┐     S3 API      ┌─────────────┐
│   Client    │◄──────────────────►│   Server    │◄───────────────►│  S3 Storage │
│  (Desktop)  │   Encrypted Data   │  (FastAPI)  │  Encrypted Blobs│ (OVH/AWS/..)│
└─────────────┘                    └─────────────┘                 └─────────────┘
      │                                   │
      │ AES-256-GCM                       │ Metadata Only
      │ Client-Side                       │ (paths, sizes, hashes)
      ▼                                   ▼
┌─────────────┐                    ┌─────────────┐
│  Local FS   │                    │   SQLite    │
│  + Index    │                    │     DB      │
└─────────────┘                    └─────────────┘
```

## Installation

```bash
# Clone the repository
git clone https://github.com/Dubrzr/file-sync-ssh.git
cd file-sync-ssh

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Install with all dependencies
pip install -e ".[all]"
```

## Quick Start

### Client Setup

```bash
# Initialize SyncAgent with a master password
syncagent init

# Unlock the keystore (required before sync operations)
syncagent unlock

# Export key for sharing with other machines
syncagent export-key

# Import key on another machine
syncagent import-key <base64-key>
```

### Server Setup

```bash
# Start the server
uvicorn syncagent.server.app:app_factory --factory --host 0.0.0.0 --port 8000

# The first visit to the web UI will prompt you to create an admin account
# Then create invitations to register client machines
```

### Environment Variables (Server)

```bash
# Required
SYNCAGENT_DB_PATH=/path/to/syncagent.db

# S3 Storage (optional, defaults to local filesystem)
SYNCAGENT_S3_BUCKET=your-bucket
SYNCAGENT_S3_ENDPOINT=https://s3.region.ovh.net
SYNCAGENT_S3_ACCESS_KEY=your-access-key
SYNCAGENT_S3_SECRET_KEY=your-secret-key
SYNCAGENT_S3_REGION=region

# Local Storage (development)
SYNCAGENT_STORAGE_PATH=/path/to/chunks
```

## Web Dashboard

The web UI provides:

- **File Browser**: View synced files with metadata (size, version, modified date)
- **Machines**: Monitor connected devices and their sync status
- **Invitations**: Generate tokens to register new machines
- **Trash**: Restore or permanently delete files

Access the dashboard at `http://localhost:8000` after starting the server.

## Security

- **Encryption**: AES-256-GCM with unique nonce per chunk
- **Key Derivation**: Argon2id with secure parameters
- **Key Storage**: OS keyring (Windows Credential Manager, macOS Keychain, Linux Secret Service)
- **Authentication**: Bearer tokens (machines), session cookies (web UI)
- **Zero-Knowledge**: Server only stores encrypted blobs and metadata hashes

## Development

```bash
# Install dev dependencies
pip install -e ".[dev]"

# Run tests
pytest tests/ -v

# Type checking
mypy src/

# Linting
ruff check src/ tests/

# Run all checks
pytest && mypy src/ && ruff check src/ tests/
```

## Project Structure

```
src/syncagent/
├── core/
│   ├── crypto.py       # AES-256-GCM encryption
│   └── chunking.py     # Content-defined chunking (FastCDC)
├── client/
│   ├── keystore.py     # Key management & OS keyring
│   ├── index.py        # Local file index (SQLite)
│   ├── watcher.py      # File system watcher
│   ├── state.py        # Sync state management
│   ├── api.py          # HTTP client for server
│   ├── sync.py         # Sync engine (push/pull)
│   └── cli.py          # Command-line interface
└── server/
    ├── app.py          # FastAPI application
    ├── database.py     # SQLAlchemy ORM operations
    ├── models.py       # Database models
    ├── storage.py      # Chunk storage (Local/S3)
    ├── web.py          # Web UI routes
    └── templates/      # Jinja2 templates
```

## Documentation

- [Specifications](docs/SPECS.md) - Complete architecture and workflows
- [API Reference](docs/api.md) - REST endpoints and WebSocket
- [Database Schema](docs/database-schema.md) - SQLite schemas

## License

MIT
