# SyncAgent - Zero Knowledge E2EE File Sync

> Synchronisation de fichiers entre machines (Windows/macOS/Linux) avec chiffrement côté client.

## Documentation

- [SPECS.md](docs/SPECS.md) - **Spécifications complètes** (architecture, workflows, code examples)
- [Architecture](docs/architecture.md) - Vue d'ensemble Zero-Knowledge
- [API REST](docs/api.md) - Endpoints et WebSocket
- [Database Schema](docs/database-schema.md) - Schémas SQLite

---

## Progression

| Phase | Description | Status |
|-------|-------------|--------|
| 1 | Crypto & Core | Done |
| 2 | Content-Defined Chunking | Done |
| 3 | Server Metadata API | Done |
| 4 | Block Storage | **Next** |
| 5 | Sync Engine | Pending |
| 6 | Web UI | Pending |
| 7 | Protocol Handler | Pending |
| 8 | Tray Icon | Pending |

---

## Phase 1: Crypto & Core [DONE]

- [x] Dérivation de clé Argon2id
- [x] Chiffrement/déchiffrement AES-GCM
- [x] Stockage sécurisé de la clé (keyring OS)
- [x] CLI: `init`, `unlock`, `export-key`, `import-key`
- [x] Tests unitaires (95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/core/crypto.py`, `src/syncagent/core/keystore.py`

---

## Phase 2: Content-Defined Chunking [DONE]

- [x] Implémentation CDC avec FastCDC
- [x] Taille: min 1MB, avg 4MB, max 8MB
- [x] Hash SHA-256 des chunks
- [x] Tests stabilité des frontières
- [x] Tests unitaires (95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/core/chunking.py`

---

## Phase 3: Server Metadata API [DONE]

- [x] FastAPI app + SQLite WAL
- [x] SQLAlchemy ORM + Alembic migrations
- [x] API REST: machines, tokens, files, chunks
- [x] Authentification Bearer token
- [x] Détection de conflits (version parente)
- [x] Soft-delete (corbeille)
- [x] Tests unitaires (95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/server/`

---

## Phase 4: Block Storage [IN PROGRESS]

- [ ] Interface abstraite `ChunkStorage`
- [ ] Implémentation `LocalFSStorage` (dev/test)
- [ ] Implémentation `S3Storage` (OVH/AWS/MinIO)
- [ ] Factory `create_storage()`
- [ ] API endpoints: upload/download chunks
- [ ] Tests unitaires avec moto (mock S3)
- [ ] Mypy strict + Ruff zero warnings

**À créer:** `src/syncagent/server/storage.py`

---

## Phase 5: Sync Engine

- [ ] File watcher (watchdog)
- [ ] Debounce 250ms + délai 3s avant sync
- [ ] Algorithme push/pull
- [ ] Gestion conflits (duplication automatique)
- [ ] SQLite local pour état client
- [ ] Reconnexion après offline (catch-up)
- [ ] Tests unitaires

**À créer:** `src/syncagent/client/watcher.py`, `src/syncagent/client/sync.py`

---

## Phase 6: Web UI

- [ ] Setup wizard (création admin)
- [ ] Login/session cookies
- [ ] File browser (métadonnées only)
- [ ] Liste conflits + résolution
- [ ] Page corbeille + restauration
- [ ] Status machines
- [ ] Gestion invitations
- [ ] CSRF protection
- [ ] Liens `syncfile://`

**À créer:** `src/syncagent/server/templates/`, `src/syncagent/server/web.py`

---

## Phase 7: Protocol Handler

- [ ] Parsing URLs `syncfile://`
- [ ] Enregistrement Windows (Registry)
- [ ] Enregistrement macOS (LaunchServices)
- [ ] Enregistrement Linux (.desktop)
- [ ] Validation sécurité (path traversal)

**À créer:** `src/syncagent/client/protocol.py`

---

## Phase 8: Tray Icon

- [ ] pystray setup
- [ ] Icônes par état (idle, syncing, error, conflict)
- [ ] Menu contextuel (sync now, open folder, quit)

**À créer:** `src/syncagent/client/tray.py`

---

## Requirements Fonctionnels

### Synchronisation
- [ ] Sync bidirectionnel via serveur
- [ ] Détection automatique changements (file watcher + scan backup 5min)
- [ ] Sync incrémental (CDC)
- [ ] Resume après interruption
- [ ] Intégrité SHA-256 par chunk

### Chiffrement (E2EE)
- [x] Chiffrement côté client uniquement
- [x] Clé dérivée d'un mot de passe maître
- [x] Partage clé entre machines (export/import)
- [x] AES-256-GCM

### Conflits
- [ ] Détection automatique
- [ ] Duplication: `fichier (conflit - machine).ext`
- [ ] Résolution manuelle

### Stockage
- [ ] Block storage S3-compatible
- [x] Mode local FS (dev/test)
- [ ] Chunks liés au fichier (pas de dédup v1)
- [ ] Suppression chunks à purge corbeille

### Corbeille
- [ ] Rétention 30 jours (configurable)
- [ ] Restauration via Web UI
- [ ] Purge automatique

### Authentification
- [x] Machines: Bearer token
- [ ] Web UI: session cookie HttpOnly
- [x] Tokens hashés côté serveur
- [ ] Admin via setup wizard
- [ ] Invitations usage unique (expire 24h)

---

## Requirements Non-Fonctionnels

- [x] Code coverage ≥ 95%
- [x] Mypy strict
- [x] Ruff zero warnings
- [x] Conventional Commits
- [x] Docstrings fonctions publiques
- [ ] Tests d'intégration client ↔ serveur
