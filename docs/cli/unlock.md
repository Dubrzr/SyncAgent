# syncagent unlock

Unlock the SyncAgent keystore.

## Usage

```bash
syncagent unlock
```

## Description

Decrypts the keystore using the master password.
This verifies that the password is correct and displays the key ID.

## Behavior

### Interactive Prompts

1. **Master password**: Used to decrypt the keystore

### Success Output

```
Keystore unlocked successfully!
Key ID: <key-id>
```

### Error Cases

| Condition | Message | Exit Code |
|-----------|---------|-----------|
| Not initialized | "Error: SyncAgent not initialized. Run 'syncagent init' first." | 1 |
| Wrong password | "Error: Invalid password or corrupted keyfile." | 1 |

## Use Cases

- Verify that the master password is correct
- Check the key ID for troubleshooting
- Validate keystore integrity
