# syncagent sync

Synchronize files with the server.

## Usage

```bash
syncagent sync [--watch] [--no-progress]
```

## Options

| Option | Description |
|--------|-------------|
| `--watch`, `-w` | Watch for changes and sync continuously |
| `--no-progress` | Disable progress output |

## Description

Uploads local changes and downloads remote changes.
Files are encrypted client-side before upload.

## Behavior

### Prerequisites

- Must have run `syncagent init` first
- Must have run `syncagent register` first
- Prompts for master password to unlock keystore

### Single Sync Mode (default)

1. Scans local folder for new/modified/deleted files
2. Fetches list of remote changes from server
3. Uploads local changes
4. Downloads remote changes
5. Shows summary and exits

### Watch Mode (--watch)

1. Performs initial sync (same as single mode)
2. Watches sync folder for file system events
3. Syncs changes as they occur
4. Continues until Ctrl+C

### Output Format

```
Syncing with <server-url>...
Sync folder: <sync-folder>

  ↑ file1.txt
  ↑ docs/file2.txt
  ↓ remote-file.txt

Sync complete: 2 uploaded, 1 downloaded, 0 deleted, 0 conflicts
```

Indicators:
- `↑` Upload
- `↓` Download
- `✗` Delete
- `!` Conflict

### Files Created

- `~/.syncagent/state.db` - SQLite database tracking synced files

### Success Output

With changes:
```
Sync complete: X uploaded, Y downloaded, Z deleted, N conflicts
```

No changes:
```
Everything is up to date.
```

### Error Cases

| Condition | Message | Exit Code |
|-----------|---------|-----------|
| Not initialized | "Error: SyncAgent not initialized. Run 'syncagent init' first." | 1 |
| Not registered | "Error: Not registered with a server. Run 'syncagent register' first." | 1 |
| Wrong password | "Error: Invalid password or corrupted keyfile." | 1 |
| Server unreachable | "Server unreachable: <error>" (then retries) | - |

### Network Handling

- Automatically waits and retries when server is unreachable
- Shows "Waiting for server to come back online..."
- Resumes when connection is restored

### Conflict Handling

When both local and remote changes exist for the same file:
- Creates a `.conflict-<timestamp>` copy
- Shows conflict in summary
- Sends desktop notification

## State Tracking

Files are tracked in state.db with:
- `path` - Relative path from sync folder
- `local_mtime` - Last modification time when synced
- `local_size` - File size when synced
- `server_version` - Version number on server
- `chunk_hashes` - Hashes of file chunks (for resume)

A file is considered:
- **NEW**: Exists on disk but not in state
- **MODIFIED**: Exists with different mtime/size than state
- **DELETED**: In state but not on disk
- **SYNCED**: Matches state exactly
