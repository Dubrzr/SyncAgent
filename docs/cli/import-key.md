# syncagent import-key

Import an encryption key from another device.

## Usage

```bash
syncagent import-key <KEY>
```

## Arguments

| Argument | Required | Description |
|----------|----------|-------------|
| KEY | Yes | Base64-encoded encryption key from another device |

## Description

Imports an encryption key exported from another device. This replaces the current encryption key, allowing this device to decrypt files encrypted by the source device.

## Authentication

Requires master password to:
1. Unlock the current keystore
2. Re-encrypt the imported key with your password

## Output

```
Enter master password: ********
Encryption key imported successfully!
New Key ID: <uuid>
```

## Error Cases

| Condition | Exit Code | Message |
|-----------|-----------|---------|
| Not initialized | 1 | "Error: SyncAgent not initialized. Run 'syncagent init' first." |
| Wrong password | 1 | "Error: Invalid password or corrupted keyfile" |
| Invalid base64 | 1 | "Error: Invalid key format: not valid base64" |
| Wrong key length | 1 | "Error: Invalid key: must be 32 bytes, got N" |

## Notes

- After import, a new Key ID is generated
- The imported key is re-encrypted with your local password
- Both devices must use the same key for E2EE sync to work
