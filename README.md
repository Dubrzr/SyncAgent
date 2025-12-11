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

### From Source (Development)

```bash
# Clone the repository
git clone https://github.com/Dubrzr/file-sync-ssh.git
cd file-sync-ssh

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate  # Windows
# source .venv/bin/activate  # Linux/macOS

# Install client only
pip install -e .

# Install with server dependencies
pip install -e ".[server]"

# Install with all dependencies (client + server + dev)
pip install -e ".[all]"

# Install with optional tray icon support
pip install -e ".[tray]"
```

### Client Only (pip)

```bash
# Install from PyPI (when published)
pip install syncagent

# Or install directly from GitHub
pip install git+https://github.com/Dubrzr/file-sync-ssh.git
```

## Quick Start

### 1. Server Setup

First, set up the server (can be on a remote machine or locally):

```bash
# Start the server
uvicorn syncagent.server.app:app --host 0.0.0.0 --port 8000

# Open http://localhost:8000 in your browser
# Create an admin account on first visit
# Go to "Invitations" and create an invitation token for your client
```

### 2. Client Setup

On each machine you want to sync:

```bash
# Initialize SyncAgent with a master password
# This creates your encryption key (stored in OS keyring)
syncagent init

# Files will be synced to ~/SyncAgent by default
```

### 3. Register with Server

```bash
# Register this machine with the server using an invitation token
syncagent register --server https://your-server:8000 --token <invitation-token>
```

### 4. Share Key with Other Machines

To sync the same files on multiple machines, they need the same encryption key:

```bash
# On the first machine: export the key
syncagent export-key
# Output: base64-encoded key (keep this secret!)

# On other machines: import the key
syncagent import-key <base64-key>
```

### 5. Start Syncing

```bash
# Unlock the keystore (required before sync operations)
syncagent unlock

# Start the sync daemon
syncagent sync

# Or run with system tray icon (requires pystray)
syncagent tray
```

### CLI Commands Reference

```bash
syncagent init              # Initialize keystore with master password
syncagent unlock            # Unlock keystore for sync operations
syncagent export-key        # Export encryption key (base64)
syncagent import-key KEY    # Import encryption key from another machine
syncagent register          # Register machine with server
syncagent sync              # Start sync daemon
syncagent tray              # Start with system tray icon
syncagent register-protocol # Register syncfile:// URL handler
syncagent protocol-status   # Check if URL handler is registered
```

## Server Deployment

### Environment Variables

```bash
# Database path (default: ./syncagent.db)
SYNCAGENT_DB_PATH=/path/to/syncagent.db

# S3 Storage (optional, defaults to local filesystem)
SYNCAGENT_S3_BUCKET=your-bucket
SYNCAGENT_S3_ENDPOINT=https://s3.region.ovh.net
SYNCAGENT_S3_ACCESS_KEY=your-access-key
SYNCAGENT_S3_SECRET_KEY=your-secret-key
SYNCAGENT_S3_REGION=region

# Local Storage path (default: ./storage)
SYNCAGENT_STORAGE_PATH=/path/to/chunks
```

### Production Deployment

```bash
# Using gunicorn with uvicorn workers
pip install gunicorn
gunicorn syncagent.server.app:app -w 4 -k uvicorn.workers.UvicornWorker -b 0.0.0.0:8000

# With HTTPS (recommended)
gunicorn syncagent.server.app:app -w 4 -k uvicorn.workers.UvicornWorker \
  -b 0.0.0.0:443 --certfile=cert.pem --keyfile=key.pem
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
│   ├── tray.py         # System tray icon (pystray)
│   ├── protocol.py     # syncfile:// URL handler
│   └── cli.py          # Command-line interface
└── server/
    ├── app.py          # FastAPI application entry point
    ├── database.py     # SQLAlchemy ORM operations
    ├── models.py       # Database models
    ├── schemas.py      # Pydantic request/response models
    ├── storage.py      # Chunk storage (Local/S3)
    ├── api/            # REST API routes (JSON)
    │   ├── deps.py     # FastAPI dependencies
    │   ├── machines.py # Machine management
    │   ├── files.py    # File operations
    │   ├── trash.py    # Trash operations
    │   └── chunks.py   # Chunk storage
    └── web/            # Web UI routes (HTML)
        ├── router.py   # Dashboard routes
        └── templates/  # Jinja2 templates
```

## Documentation

- [Specifications](docs/SPECS.md) - Complete architecture and workflows
- [API Reference](docs/api.md) - REST endpoints and WebSocket
- [Database Schema](docs/database-schema.md) - SQLite schemas

## License

MIT
