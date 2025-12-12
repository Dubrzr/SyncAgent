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
| 10 | Conflict Management | Done |
| 11 | Trash Auto-Purge | Done |
| 12 | Resume Sync | Done |
| 13 | Integration Tests | Done |
| 14 | Sync Optimizations | Pending |
| 15 | Real-Time Local Dashboard | Pending |

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


## Phase 10: Conflict Management [DONE]

**Objectif:** Détecter et signaler les conflits de synchronisation à l'utilisateur

### 10.1 - Détection intelligente (éviter faux conflits)
- [x] Si hash identique des deux côtés → auto-résoudre silencieusement (pas de conflit réel)
- [x] Si un seul côté modifié depuis dernier sync → pas de conflit, prendre la modification

### 10.2 - Création copie conflictuelle
- [x] Format: `fichier.conflict-YYYYMMDD-HHMMSS-{machine}.ext`
- [x] Conserver le fichier serveur, renommer le local en `.conflict-*`
- [x] Logger l'événement avec détails (versions, timestamps, machines)

### 10.3 - Notification système
- [x] Notification OS (Windows toast, macOS notification, Linux notify-send)
- [x] Message: "Conflit détecté: {filename} - Vérifiez le fichier .conflict-*"
- [x] Tray icon: indicateur visuel si conflits (TrayStatus.CONFLICT déjà implémenté)

- [x] Tests unitaires (33 tests pour sync + notifications)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/sync.py`, `src/syncagent/client/notifications.py`, `src/syncagent/client/cli.py`

---

## Phase 11: Trash Auto-Purge & Configuration [DONE]

**Objectif:** Automatiser le nettoyage de la corbeille avec configuration

- [x] Variable d'environnement `SYNCAGENT_TRASH_RETENTION_DAYS` (défaut: 30)
- [x] Fix: Suppression explicite des chunks dans `purge_trash()` (bug actuel)
- [x] Scheduler APScheduler pour purge automatique (quotidienne à 3h)
- [x] CLI: `syncagent server purge-trash [--older-than-days N]` pour cron/manuel
- [x] API Admin: `POST /api/admin/purge-trash`
- [x] Suppression chunks du storage S3/local lors de la purge
- [x] Tests unitaires (19 tests, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/server/app.py`, `src/syncagent/server/scheduler.py`, `src/syncagent/server/api/admin.py`, `src/syncagent/server/database.py`, `src/syncagent/server/web/router.py`

---

## Phase 12: Resume Sync & Robustesse [DONE]

**Objectif:** Permettre la reprise des transferts interrompus au niveau chunk

- [x] Table `upload_progress` (file_path, chunk_hashes, uploaded_hashes, total_chunks, uploaded_chunks)
- [x] Écriture atomique downloads: `fichier.tmp` → rename après validation
- [x] Tracking progression upload par chunk (pas seulement par fichier)
- [x] Retry avec backoff exponentiel (1s, 2s, 4s, 8s, max 60s)
- [x] Config `max_retries` (défaut: 5) pour uploads/downloads
- [x] Validation checksum avant resume (si hashes changent, restart upload)
- [x] Tests unitaires (26 tests pour Phase 12, 95%+ coverage)
- [x] Mypy strict + Ruff zero warnings

**Fichiers:** `src/syncagent/client/sync.py`, `src/syncagent/client/state.py`

---

## Phase 13: Integration Tests [DONE]

**Objectif:** Valider le workflow complet client ↔ serveur end-to-end

- [x] Fixture pytest: Serveur de test avec DB in-memory + storage local temp
- [x] Test: `init` → `register` → upload fichier → download sur autre client
- [x] Test: Modification simultanée sur 2 clients → détection conflit
- [x] Test: Suppression fichier → corbeille → restauration → re-sync
- [x] Test: Gros fichier (100MB+) chunked upload/download
- [x] CI: Job GitHub Actions séparé pour tests d'intégration
- [x] 21 tests d'intégration e2e

**Fichiers:** `tests/integration/conftest.py`, `tests/integration/test_sync_e2e.py`, `tests/integration/test_conflict_e2e.py`, `.github/workflows/integration.yml`

---

## Phase 14: Sync Optimizations (State of the Art)

**Objectif:** Atteindre les performances des solutions cloud comme GDrive/OneDrive/Dropbox

### Haute Priorité

- [ ] **Delta sync (rsync-like)**: Ne transférer que les blocs modifiés d'un fichier au lieu du fichier entier
  - Utiliser rolling checksum (Rabin fingerprint) pour détecter les parties inchangées
  - Réduire drastiquement la bande passante pour les gros fichiers modifiés
- [ ] **Sync incrémental serveur**: API `/api/changes?since=timestamp` au lieu de lister tous les fichiers
  - Table `change_log` avec (file_id, action, timestamp)
  - Réduire la charge serveur et le temps de sync initial
- [ ] **Résolution de conflits interactive**: UI pour choisir quelle version garder
  - Créer copie locale `fichier.conflict-<machine>-<timestamp>.ext`
  - Comparaison côte-à-côte des versions

### Moyenne Priorité

- [ ] **Sync sélectif**: Choisir quels dossiers synchroniser
  - Config `.syncfolders` pour inclure/exclure des chemins
  - UI pour gérer les dossiers synchronisés
- [ ] **Fichiers à la demande (placeholder files)**: Comme OneDrive "Files On-Demand"
  - Fichiers non téléchargés localement, téléchargement à l'ouverture
  - Nécessite intégration OS (Cloud Files API Windows, FUSE Linux)
- [ ] **Versioning accessible**: Historique des versions via UI
  - `GET /api/files/{path}/versions` - liste des versions
  - Restauration d'une version spécifique
- [ ] **Pause/Resume uploads**: Reprendre un upload interrompu au niveau chunk
  - Stockage de la progression par chunk
  - Vérification des chunks déjà uploadés avant reprise

### Basse Priorité

- [ ] **Bandwidth throttling**: Limiter la bande passante utilisée
  - Config `max_upload_speed`, `max_download_speed`
- [ ] **LAN sync (peer-to-peer)**: Sync direct entre machines sur le même réseau
  - Découverte mDNS/Bonjour
  - Transfert direct sans passer par le serveur

**Fichiers:** `src/syncagent/client/sync.py`, `src/syncagent/client/delta.py`, `src/syncagent/server/api/changes.py`

---

## Phase 15: Real-Time Server Dashboard (WebUI as Single Interface)

**Objectif:** Enrichir le dashboard serveur existant avec des infos temps réel des clients (progression, conflits, actions)

### Architecture
```
┌──────────────┐                      ┌───────────────┐
│   Browser    │◄─── WebSocket ──────►│    Server     │
│  (WebUI)     │   (temps réel)       │  (FastAPI)    │
└──────────────┘                      └───────┬───────┘
                                              │
                                              │ WebSocket
                                              │ (events)
                                              ▼
                                      ┌───────────────┐
                                      │    Client     │
                                      │ (syncagent)   │
                                      └───────────────┘
```

### 15.1 - Client → Server: Event Reporting
- [ ] WebSocket client dans SyncEngine pour envoyer les events au serveur
- [ ] Events émis par le client:
  - `sync_started` (machine_id, file_count)
  - `sync_progress` (machine_id, file_path, current_chunk, total_chunks, bytes)
  - `sync_completed` (machine_id, files_uploaded, files_downloaded)
  - `sync_error` (machine_id, error_message)
  - `conflict_detected` (machine_id, file_path, local_version, server_version)
- [ ] Reconnexion automatique WebSocket avec backoff
- [ ] File d'attente locale si déconnecté (replay on reconnect)

### 15.2 - Server: WebSocket Hub
- [ ] Endpoint WebSocket `/ws/events` pour les clients (machines)
- [ ] Endpoint WebSocket `/ws/dashboard` pour le browser (WebUI)
- [ ] Hub central qui relaie les events clients → browsers
- [ ] Stockage en mémoire de l'état courant de chaque machine
- [ ] API REST `/api/machines/{id}/status` pour état actuel (fallback polling)

### 15.3 - Dashboard WebUI: Real-Time Updates
- [ ] Connexion WebSocket depuis le browser vers `/ws/dashboard`
- [ ] Page "Activity" avec:
  - **Live Sync Progress**: Barres de progression par machine/fichier
  - **Transfer Queue**: Fichiers en cours de transfert (toutes machines)
  - **Activity Log**: Stream temps réel des événements
- [ ] Mise à jour de la page "Machines" en temps réel:
  - Status live (syncing, idle, error, offline)
  - Dernier fichier synchronisé
  - Vitesse de transfert

### 15.4 - Tray Icon Integration
- [ ] Clic gauche → Ouvre le dashboard serveur (URL configurée)
- [ ] Clic droit → Menu contextuel (comme maintenant)
- [ ] Le client continue de tourner en background

### 15.5 - Actions depuis la WebUI (optionnel, v2)
- [ ] Bouton "Sync Now" pour forcer une sync sur une machine
- [ ] Bouton "Pause/Resume" par machine
- [ ] Nécessite un channel de commandes Server → Client

### Tests & Qualité
- [ ] Tests unitaires WebSocket hub
- [ ] Tests intégration client ↔ server WebSocket
- [ ] Mypy strict + Ruff zero warnings

**Fichiers:**
- Server: `src/syncagent/server/websocket.py`, `src/syncagent/server/web/templates/activity.html`
- Client: `src/syncagent/client/sync.py` (ajout WebSocket reporter), `src/syncagent/client/tray.py`

**Dépendances:** Aucune nouvelle (websockets déjà présent)

---

## Requirements Fonctionnels

### Synchronisation
- [x] Sync bidirectionnel via serveur
- [x] Détection automatique changements (file watcher + scan backup 5min)
- [x] Sync incrémental (CDC)
- [x] Resume après interruption
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
- [x] Suppression chunks à purge corbeille

### Corbeille
- [x] Rétention 30 jours (configurable via `SYNCAGENT_TRASH_RETENTION_DAYS`)
- [x] Restauration via Web UI
- [x] Purge automatique (APScheduler quotidien à 3h)

### Authentification
- [x] Machines: Bearer token
- [x] Web UI: session cookie HttpOnly
- [x] Tokens hashés côté serveur
- [x] Admin via setup wizard
- [x] Invitations usage unique (expire 24h)

### Autres (Julien)
- [x] Possibilité d'enlever une machine depuis la wui
- [x] On doit pouvoir configurer dans le syncagent register le nom de la machine (entrée pour le nom par défaut)
- [x] Voir des statistiques sur chaque machine dans la wui: nombre de fichiers exactement synchronisés sur cette machine, place utilisée sur le storage
- [ ] Que se passe-t-il si un fichier est supprimé, puis à sa place (même path/nom de fichier) un nouveau est créé, et que j'essaye de restaurer le fichier supprimé (qui est censé arrivé à son original location?)
- [x] L'affichage logique des fichiers dans l'UI doit gérer une hierarchie de dossiers/fichiers, pas tous les fichiers à plat
- [x] Quand le serveur est lancé; il doit indiquer où il stocke ses chunks
- [x] La commande sync doit afficher une barre de progression des fichiers actuellement en cours de synchro
- [x] Détection et synchronisation des fichiers supprimés localement
- [x] Les logs du serveur doivent aller dans un fichier de logs en + de la sortie standard
- [ ] On peut considérer que la seule interface valable pour effectuer des actions ou voir des infos sur les processus locaux ou distants est la webui; typiquement même pour l'avancée de transferts je pense que ça pourrait être intéressant; et faire en sorte que si on a une icon system tray et qu'on clique dessus, ça devrait ouvrir la page web; de sorte à ce que l'on ait pas du tout de à dev d'ui locale → **Voir Phase 15** 

---

## Requirements Non-Fonctionnels

- [x] Code coverage ≥ 95%
- [x] Mypy strict
- [x] Ruff zero warnings
- [x] Conventional Commits
- [x] Docstrings fonctions publiques
- [ ] Tests d'intégration client ↔ serveur

