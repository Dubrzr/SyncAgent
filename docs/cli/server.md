# syncagent server

Start the SyncAgent server.

## Usage

```bash
syncagent server [OPTIONS]
```

## Options

| Option | Description | Default |
|--------|-------------|---------|
| `--host` | Host to bind to | 0.0.0.0 |
| `--port` | Port to listen on | 8000 |
| `--db-path` | Path to SQLite database | SYNCAGENT_DB_PATH or ./syncagent.db |
| `--storage-path` | Path to chunk storage | SYNCAGENT_STORAGE_PATH or ./storage |
| `--reload` | Enable auto-reload for development | False |

## Description

Starts the SyncAgent server using uvicorn. The server provides:
- REST API for file synchronization
- WebSocket for real-time status updates
- Web dashboard for administration

## Environment Variables

| Variable | Description |
|----------|-------------|
| `SYNCAGENT_DB_PATH` | Database file path |
| `SYNCAGENT_STORAGE_PATH` | Chunk storage directory |
| `SYNCAGENT_TRASH_RETENTION_DAYS` | Days to keep deleted files (default: 30) |

## Examples

```bash
# Start with defaults (localhost:8000)
syncagent server

# Start on specific port
syncagent server --port 9000

# Start with custom paths
syncagent server --db-path /var/lib/syncagent/db.sqlite --storage-path /var/lib/syncagent/chunks

# Development mode with auto-reload
syncagent server --reload
```

## First Run

On first run, the server will:
1. Create the database file
2. Create the storage directory
3. Display the admin setup URL

Open http://localhost:8000 to create an admin account.
