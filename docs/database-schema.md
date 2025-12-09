# Schéma Base de Données

## Serveur (SQLite WAL)

### machines
```sql
CREATE TABLE machines (
    id INTEGER PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,      -- Nom unique (alphanum, tirets, underscores)
    platform TEXT NOT NULL,          -- windows, darwin, linux
    created_at DATETIME NOT NULL,
    last_seen DATETIME NOT NULL
);
```

### tokens
```sql
CREATE TABLE tokens (
    id INTEGER PRIMARY KEY,
    machine_id INTEGER NOT NULL REFERENCES machines(id) ON DELETE CASCADE,
    token_hash TEXT UNIQUE NOT NULL,  -- SHA-256 du token
    created_at DATETIME NOT NULL,
    expires_at DATETIME,              -- NULL = jamais
    revoked BOOLEAN DEFAULT FALSE
);
```

### files
```sql
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,        -- Chemin relatif (non chiffré)
    size INTEGER NOT NULL,
    content_hash TEXT NOT NULL,       -- Hash du contenu complet
    version INTEGER DEFAULT 1,        -- Pour détection conflits
    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    updated_by INTEGER NOT NULL REFERENCES machines(id),
    deleted_at DATETIME               -- Soft-delete (corbeille)
);
```

### chunks
```sql
CREATE TABLE chunks (
    file_id INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    chunk_index INTEGER NOT NULL,     -- Ordre dans le fichier
    chunk_hash TEXT NOT NULL,         -- SHA-256 du chunk
    PRIMARY KEY (file_id, chunk_index)
);
```

### invitations (à implémenter)
```sql
CREATE TABLE invitations (
    token_hash TEXT PRIMARY KEY,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,     -- created_at + 24h
    used_by_machine_id INTEGER,
    used_at DATETIME
);
```

### admin (à implémenter)
```sql
CREATE TABLE admin (
    id INTEGER PRIMARY KEY CHECK (id = 1),  -- Un seul admin
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,            -- Argon2id
    created_at DATETIME NOT NULL
);
```

### sessions (à implémenter)
```sql
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    created_at DATETIME NOT NULL,
    expires_at DATETIME NOT NULL,
    user_agent TEXT,
    ip_address TEXT
);
```

## Client (SQLite local)

### local_files
```sql
CREATE TABLE local_files (
    id INTEGER PRIMARY KEY,
    path TEXT UNIQUE NOT NULL,
    server_file_id INTEGER,
    server_version INTEGER,
    local_mtime REAL,
    local_size INTEGER,
    local_hash TEXT,
    chunk_hashes TEXT,                -- JSON array
    status TEXT DEFAULT 'synced',     -- synced, modified, pending_upload, conflict
    last_synced_at REAL
);
```

### pending_uploads
```sql
CREATE TABLE pending_uploads (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    detected_at REAL,
    attempts INTEGER DEFAULT 0,
    last_attempt_at REAL,
    error TEXT
);
```
