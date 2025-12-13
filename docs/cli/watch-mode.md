# Watch Mode

Continuous file synchronization using filesystem monitoring.

## Usage

```bash
syncagent sync --watch
syncagent sync -w
```

## Description

Watch mode monitors the sync folder for changes and automatically syncs them to the server. It provides real-time synchronization without manual intervention.

## Behavior

### Startup
1. Performs initial full sync (same as `syncagent sync`)
2. Starts filesystem watcher on sync folder
3. Displays "Watching for changes... (Ctrl+C to stop)"

### File Events
- **Created**: New file detected → upload
- **Modified**: File content changed → upload new version
- **Deleted**: File removed → propagate deletion to server
- **Moved**: Treated as delete + create

### Output
```
Syncing with http://localhost:8000...
Sync folder: /home/user/SyncAgent

  ↑ document.txt

Sync complete: 1 uploaded, 0 downloaded, 0 deleted, 0 conflicts

Watching for changes... (Ctrl+C to stop)

Detected change: notes.txt
  ↑ notes.txt
  ✓ 1 uploaded
```

## Event Deduplication

The watcher uses mtime-aware deduplication:
- Multiple rapid changes to same file → single upload
- Events with older mtime are discarded
- Prevents duplicate uploads during save operations

## Graceful Shutdown

Press `Ctrl+C` to stop:
```
^C
Stopping...
```

The watcher:
1. Stops accepting new events
2. Completes any in-progress transfers
3. Updates final status to server
4. Exits cleanly

## Network Handling

If server becomes unreachable during watch:
1. Displays "Server unreachable" message
2. Queues pending changes locally
3. Waits for server to come back online
4. Resumes sync automatically

## Options

| Option | Description |
|--------|-------------|
| `--no-progress` | Disable per-file progress output |

## Performance

- Watcher uses efficient OS-level APIs (inotify on Linux, FSEvents on macOS, ReadDirectoryChangesW on Windows)
- Batches rapid changes to reduce server requests
- Configurable debounce delay (default: 100ms)
