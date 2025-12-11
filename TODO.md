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
| 4 | Block Storage | Done |
| 5 | Sync Engine | Done |
| 6 | Web UI | Done |
| 7 | Protocol Handler | Done |
| 8 | Tray Icon | Done |
| 9 | Manual Testing & UX Fixes | Done |
| 10 | Conflict Management | Pending |
| 11 | Trash Auto-Purge | Pending |
| 12 | Resume Sync | Pending |
| 13 | Integration Tests | Pending |

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

## Phase 4: Block Storage [DONE]

- [x] Interface abstraite `ChunkStorage`
- [x] Implémentation `LocalFSStorage` (dev/test)
- [x] Implémentation `S3Storage` (OVH/AWS/MinIO)
- [x] Factory `create_storage()`
- [x] API endpoints: upload/download chunks
- [x] Tests unitaires avec moto (mock S3)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/server/storage.py`

---

## Phase 5: Sync Engine [DONE]

- [x] File watcher (watchdog)
- [x] Debounce 250ms + délai 3s avant sync
- [x] Ignore patterns (.syncignore support)
- [x] SQLite local pour état client
- [x] HTTP client pour API serveur
- [x] Algorithme push/pull
- [x] File upload (chunking → encrypt → upload)
- [x] File download (download → decrypt → assemble)
- [x] Gestion conflits (marquage automatique)
- [x] Tests unitaires (260 tests, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/watcher.py`, `src/syncagent/client/state.py`, `src/syncagent/client/api.py`, `src/syncagent/client/sync.py`

---

## Phase 6: Web UI [DONE]

- [x] Setup wizard (création admin)
- [x] Login/session cookies
- [x] File browser (métadonnées only)
- [x] Page corbeille + restauration
- [x] Status machines
- [x] Gestion invitations
- [x] Liens `syncfile://`
- [x] Design Apple-like (Tailwind CSS)
- [x] Tests unitaires (18 tests, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/server/templates/`, `src/syncagent/server/web.py`

---

## Phase 7: Protocol Handler [DONE]

- [x] Parsing URLs `syncfile://`
- [x] Enregistrement Windows (Registry)
- [x] Enregistrement macOS (LaunchServices)
- [x] Enregistrement Linux (.desktop)
- [x] Validation sécurité (path traversal)
- [x] CLI commands: register-protocol, unregister-protocol, open-url
- [x] Tests unitaires (35 tests, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/protocol.py`

---

## Phase 8: Tray Icon [DONE]

- [x] pystray setup with optional dependency
- [x] Icônes par état (idle, syncing, error, conflict, offline, paused)
- [x] Menu contextuel (sync now, open folder, open dashboard, pause/resume, quit)
- [x] CLI command: `syncagent tray`
- [x] Tests unitaires (41 tests, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/tray.py`

---

## Phase 9: Manual tests by Julien and their resolution [DONE]

- [x] Mobile navigation hamburger menu added for responsive Web UI
- [x] "Enter master password" → "Create master password" for first-time init
- [x] "Running in pure python mode (slow)" documented in README Troubleshooting section
- [x] After init: shows next steps guidance (server setup, register, sync commands)
- [x] Sync folder created automatically at ~/SyncAgent (configurable via --sync-folder)

---


## Phase 10: Conflict Management

**Objectif:** Permettre aux utilisateurs de gérer les conflits de synchronisation

- [ ] Créer copie locale lors d'un conflit: `fichier (conflit - machine - timestamp).ext`
- [ ] Stocker métadonnées du conflit (machine source, timestamp, versions)
- [ ] API: `GET /api/conflicts` - lister les fichiers en conflit
- [ ] API: `POST /api/conflicts/{path}/resolve` - résoudre (keep_local, keep_server, keep_both)
- [ ] Web UI: Page `/conflicts` avec liste des conflits et comparaison versions
- [ ] CLI: `syncagent conflicts` (liste) et `syncagent resolve <path>` (résolution interactive)
- [ ] Tests unitaires (95%+ coverage)
- [ ] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/sync.py`, `src/syncagent/server/api/conflicts.py`, `src/syncagent/server/web/templates/conflicts.html`

---

## Phase 11: Trash Auto-Purge & Configuration

**Objectif:** Automatiser le nettoyage de la corbeille avec configuration

- [ ] Variable d'environnement `SYNCAGENT_TRASH_RETENTION_DAYS` (défaut: 30)
- [ ] Fix: Suppression explicite des chunks dans `purge_trash()` (bug actuel)
- [ ] Scheduler APScheduler pour purge automatique (quotidienne à 3h)
- [ ] CLI: `syncagent server purge-trash [--older-than-days N]` pour cron/manuel
- [ ] API Admin: `POST /api/admin/purge-trash`
- [ ] Suppression chunks du storage S3/local lors de la purge
- [ ] Tests unitaires (95%+ coverage)
- [ ] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/server/app.py`, `src/syncagent/server/scheduler.py`, `src/syncagent/server/database.py`, `src/syncagent/server/storage.py`

---

## Phase 12: Resume Sync & Robustesse

**Objectif:** Permettre la reprise des transferts interrompus au niveau chunk

- [ ] Table `upload_progress` (file_path, chunk_index, chunk_hash, uploaded_at)
- [ ] Écriture atomique downloads: `fichier.tmp` → rename après validation
- [ ] Tracking progression upload par chunk (pas seulement par fichier)
- [ ] Retry avec backoff exponentiel (1s, 2s, 4s, 8s, max 60s)
- [ ] Config `max_retry_attempts` (défaut: 5) avant marquage échec
- [ ] Validation checksum partiel avant resume download
- [ ] Tests unitaires (95%+ coverage)
- [ ] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/sync.py`, `src/syncagent/client/state.py`, `src/syncagent/client/api.py`

---

## Phase 13: Integration Tests

**Objectif:** Valider le workflow complet client ↔ serveur end-to-end

- [ ] Fixture pytest: Serveur de test avec DB in-memory + storage local temp
- [ ] Test: `init` → `register` → upload fichier → download sur autre client
- [ ] Test: Modification simultanée sur 2 clients → détection conflit
- [ ] Test: Suppression fichier → corbeille → restauration → re-sync
- [ ] Test: Interruption réseau simulée → resume sync
- [ ] Test: Gros fichier (100MB+) chunked upload/download
- [ ] CI: Job GitHub Actions séparé pour tests d'intégration
- [ ] Coverage minimum 90% sur scénarios e2e

**Fichiers:** `tests/integration/conftest.py`, `tests/integration/test_sync_e2e.py`, `tests/integration/test_conflict_e2e.py`, `.github/workflows/integration.yml`

---

## Requirements Fonctionnels

### Synchronisation
- [x] Sync bidirectionnel via serveur
- [x] Détection automatique changements (file watcher + scan backup 5min)
- [x] Sync incrémental (CDC)
- [ ] Resume après interruption
- [x] Intégrité SHA-256 par chunk

### Chiffrement (E2EE)
- [x] Chiffrement côté client uniquement
- [x] Clé dérivée d'un mot de passe maître
- [x] Partage clé entre machines (export/import)
- [x] AES-256-GCM

### Conflits
- [x] Détection automatique (version parente)
- [ ] Duplication: `fichier (conflit - machine).ext`
- [ ] Résolution manuelle

### Stockage
- [x] Block storage S3-compatible
- [x] Mode local FS (dev/test)
- [x] Chunks liés au fichier (pas de dédup v1)
- [ ] Suppression chunks à purge corbeille

### Corbeille
- [~] Rétention 30 jours (configurable) - *30j hardcodé, pas encore configurable*
- [x] Restauration via Web UI
- [ ] Purge automatique

### Authentification
- [x] Machines: Bearer token
- [x] Web UI: session cookie HttpOnly
- [x] Tokens hashés côté serveur
- [x] Admin via setup wizard
- [x] Invitations usage unique (expire 24h)

### Autres (Julien)
- [x] Possibilité d'enlever une machine depuis la wui
- [ ] Voir des statistiques sur chaque machine dans la wui: nombre de fichiers exactement synchronisés sur cette machine, place utilisée sur le storage
---

## Requirements Non-Fonctionnels

- [x] Code coverage ≥ 95%
- [x] Mypy strict
- [x] Ruff zero warnings
- [x] Conventional Commits
- [x] Docstrings fonctions publiques
- [ ] Tests d'intégration client ↔ serveur

