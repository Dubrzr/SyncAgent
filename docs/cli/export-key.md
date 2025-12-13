# syncagent export-key

Export the encryption key for sharing with other devices.

## Usage

```bash
syncagent export-key
```

## Description

Exports the encryption key as a base64-encoded string. This key is required for other devices to decrypt files synced from this device.

## Authentication

Requires master password to unlock the keystore before exporting.

## Output

```
Enter master password: ********

Encryption key (keep secret!):
<base64-encoded-key>
```

## Error Cases

| Condition | Exit Code | Message |
|-----------|-----------|---------|
| Not initialized | 1 | "Error: SyncAgent not initialized. Run 'syncagent init' first." |
| Wrong password | 1 | "Error: Invalid password or corrupted keyfile" |

## Security

- The exported key is sensitive - anyone with this key can decrypt your files
- Never share the key over insecure channels
- Consider using secure methods like QR codes or encrypted messaging

## Example Workflow

```bash
# On Device A (source)
syncagent export-key
# Copy the output key securely

# On Device B (destination)
syncagent init
syncagent import-key <copied-key>
syncagent register --server http://... --token ...
```
