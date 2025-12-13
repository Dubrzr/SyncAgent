# syncagent init

Initialize a new SyncAgent keystore.

## Usage

```bash
syncagent init
```

## Description

Creates a new encryption key and stores it securely in the config directory (~/.syncagent).
The user is prompted to create a master password and choose a sync folder.

## Behavior

### Interactive Prompts

1. **Master password**: Prompted twice for confirmation. Used to encrypt the keystore.
2. **Sync folder**: Path where files will be synchronized. Created if doesn't exist.

### Files Created

- `~/.syncagent/keyfile.json` - Encrypted keystore containing the encryption key
- `~/.syncagent/config.json` - Configuration file with sync_folder path

### Success Output

```
SyncAgent initialized successfully!
Key ID: <key-id>
Config directory: ~/.syncagent
Sync folder: <sync-folder-path>
```

### Error Cases

| Condition | Message | Exit Code |
|-----------|---------|-----------|
| Already initialized | "Error: SyncAgent already initialized." | 1 |
| Password mismatch | "Error: Passwords do not match." | 1 |
| Invalid sync folder path | "Error: Cannot create sync folder." | 1 |

## Post-Init Steps

After init, the user should:
1. Start the server
2. Get an invitation token from the admin
3. Run `syncagent register`
