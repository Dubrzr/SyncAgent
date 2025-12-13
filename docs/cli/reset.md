# syncagent reset

Reset SyncAgent configuration.

## Usage

```bash
syncagent reset [--force]
```

## Options

| Option | Description |
|--------|-------------|
| `--force` | Skip confirmation prompt |

## Description

Deletes the config directory (~/.syncagent) to allow re-initialization.
This removes the encryption key and server registration.

**WARNING**: The sync folder and synced files are NOT deleted.

## Behavior

### Without --force

1. Shows warning about what will be deleted
2. Asks for confirmation (y/n)
3. If confirmed, removes ~/.syncagent directory

### With --force

Removes ~/.syncagent directory without confirmation.

### What Gets Deleted

- `~/.syncagent/keyfile.json` - Encryption key
- `~/.syncagent/config.json` - Configuration
- `~/.syncagent/state.db` - Sync state

### What Is Preserved

- Sync folder and all files in it
- Any exported encryption keys

### Success Output

```
SyncAgent configuration has been reset.
Run 'syncagent init' to set up again.
```

### Error Cases

| Condition | Message | Exit Code |
|-----------|---------|-----------|
| Not initialized | "Nothing to reset. SyncAgent is not initialized." | 0 |
| Cannot delete | "Error deleting config directory: <error>" | 1 |
