# Network Resilience

How SyncAgent handles network failures and recovery.

## Overview

SyncAgent is designed to handle intermittent network connectivity gracefully. It uses automatic retries, exponential backoff, and resumable transfers.

## Server Unreachable

When the server cannot be reached:

```
Server unreachable: Connection refused
Waiting for server to come back online...
```

The client will:
1. Retry connection with exponential backoff
2. Wait indefinitely until server is available
3. Resume sync automatically when connection restored

```
Server is back online!
Syncing...
```

## Retry Strategy

| Attempt | Delay |
|---------|-------|
| 1 | 1 second |
| 2 | 2 seconds |
| 3 | 4 seconds |
| 4 | 8 seconds |
| 5+ | 30 seconds (max) |

## Resumable Transfers

### Upload Resume
- Large files are uploaded in chunks (1MB default)
- If upload fails mid-transfer, only remaining chunks are uploaded
- Server tracks which chunks have been received

### Download Resume
- Downloads also use chunked transfers
- Existing chunks are verified by hash
- Only missing chunks are downloaded

## Network Exceptions Handled

- `httpx.ConnectError` - Server not reachable
- `httpx.TimeoutException` - Request timed out
- `httpx.RemoteProtocolError` - Connection dropped
- `OSError` - Network interface issues

## Status Updates

During network issues, the status reporter shows:
- State: `OFFLINE` when server unreachable
- State: `SYNCING` when connection restored

## Configuration

Network behavior can be adjusted via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `SYNCAGENT_RETRY_MAX_DELAY` | 30 | Maximum retry delay in seconds |
| `SYNCAGENT_CONNECT_TIMEOUT` | 10 | Connection timeout in seconds |
| `SYNCAGENT_READ_TIMEOUT` | 30 | Read timeout in seconds |
