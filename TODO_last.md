# Remaining Test Coverage

## CRITICAL (Breaking production workflows)

- [ ] **Network Resilience**
  - Sync when server is down → auto-retry
  - Network interruption during upload/download
  - Resume partial uploads (chunk-level)
  - Connection lost mid-sync recovery

- [ ] **Watch Mode**
  - `syncagent sync --watch` basic functionality
  - File system event detection
  - Ctrl+C graceful shutdown
  - Watch mode + network reconnect

- [ ] **Export-key / Import-key CLI** (only used internally)
  - Dedicated CLI tests for export-key
  - Dedicated CLI tests for import-key
  - Error cases (wrong password, invalid key)

- [ ] **Server Command**
  - `syncagent server` start tests
  - Custom port, db-path, storage-path options

## HIGH Priority

- [ ] **State Database Recovery**
  - Corrupted state.db handling
  - Missing state.db → full re-sync
  - Corrupted keyfile.json recovery

- [ ] **Filesystem Errors**
  - Permission denied on read/write
  - Disk full during download
  - File locked by another process

- [ ] **Partial Sync Resume**
  - Upload interrupted at chunk N
  - Download interrupted mid-file
  - Resume uses existing chunks

- [ ] **Advanced Multi-client**
  - 4+ clients syncing
  - Conflict with >2 clients modifying same file
  - Different encryption keys (should fail gracefully)

## MEDIUM Priority

- [ ] **Special Characters in Paths**
  - Emoji in filenames
  - Unicode (Chinese, Arabic, etc.)
  - Case sensitivity (File.txt vs file.txt)

- [ ] **Deletion Edge Cases**
  - Delete during upload of same file
  - Delete directory with files
  - Delete and re-create same file

- [ ] **Password Edge Cases**
  - Empty password rejection
  - Very long passwords
  - Special characters in password

## LOW Priority

- [ ] **Performance/Stress Tests**
  - 1000+ files sync
  - Files >1GB
  - Deeply nested directories

- [ ] **Disk Space/Quota**
  - Low disk space handling
  - Server quota enforcement
