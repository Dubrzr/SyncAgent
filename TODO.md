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
| 15 | Event-Driven Sync Architecture | Pending |

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

## Phase 14: Sync Optimizations

**Objectif:** Optimiser les performances de synchronisation (bande passante et charge serveur)

### 14.1 - Delta Sync (rsync-like)

- [ ] **Rolling checksum** : Utiliser Rabin fingerprint pour détecter les parties inchangées
- [ ] **Signature de fichier** : Générer une signature des blocs existants côté serveur
- [ ] **Delta computation** : Calculer uniquement les blocs modifiés à transférer
- [ ] **Réduction bande passante** : Ne transférer que les différences pour gros fichiers modifiés

### 14.2 - Sync Incrémental Serveur

- [ ] **Table `change_log`** : (file_id, action, timestamp, machine_id)
- [ ] **API `/api/changes?since=timestamp`** : Retourne uniquement les changements depuis le dernier sync
- [ ] **Cursor de synchronisation** : Chaque client garde son curseur de dernière sync
- [ ] **Cleanup automatique** : Purge des entrées change_log anciennes (> 30 jours)

### Tests & Qualité

- [ ] Tests unitaires delta sync
- [ ] Tests performance avec gros fichiers (100MB+ avec petites modifications)
- [ ] Mypy strict + Ruff zero warnings

**Fichiers:**
- `src/syncagent/core/delta.py` (nouveau)
- `src/syncagent/server/api/changes.py` (nouveau)
- `src/syncagent/server/models.py` (ajout ChangeLog)

---

## Phase 15: Event-Driven Sync Architecture

**Objectif:** Implémenter une architecture de synchronisation event-driven avec coordinator central, WebSocket bidirectionnel, et dashboard temps réel (inspirée de Dropbox/Syncthing)

### Architecture Cible

```
┌──────────────┐     ┌─────────────────┐     ┌──────────────┐
│   Watcher    │────►│   Event Queue   │◄────│  WebSocket   │
│   (local)    │     │   (local)       │     │  (serveur)   │
└──────────────┘     └────────┬────────┘     └──────────────┘
                              │
                              ▼
                     ┌─────────────────┐
                     │   Coordinator   │
                     │  (orchestrator) │
                     └────────┬────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ┌────────────┐  ┌────────────┐  ┌────────────┐
       │  Upload    │  │  Download  │  │  Delete    │
       │  Worker    │  │  Worker    │  │  Worker    │
       └────────────┘  └────────────┘  └────────────┘
              │               │               │
              └───────────────┴───────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
       ┌────────────┐  ┌────────────┐  ┌────────────┐
       │  State DB  │  │  WS Client │  │  Dashboard │
       │  (local)   │  │  (report)  │  │  (WebUI)   │
       └────────────┘  └────────────┘  └────────────┘
```

### 15.1 - Event Queue System

- [ ] **SyncEvent dataclass** : Représente un événement de sync (type, path, source, timestamp, priority)
- [ ] **EventQueue class** : Queue thread-safe avec priorités
  - Priorités : DELETE > UPLOAD > DOWNLOAD (éviter transferts inutiles)
  - Deduplication : Un seul event par path (le plus récent)
  - Persistence optionnelle (SQLite) pour survie aux redémarrages
- [ ] **Event types** :
  - `LOCAL_CREATED`, `LOCAL_MODIFIED`, `LOCAL_DELETED`
  - `REMOTE_CREATED`, `REMOTE_MODIFIED`, `REMOTE_DELETED`
  - `TRANSFER_COMPLETE`, `TRANSFER_FAILED`

### 15.2 - Coordinator (Orchestrateur)

- [ ] **SyncCoordinator class** : Chef d'orchestre central
  - Lit les events de la queue
  - Applique les règles de décision (matrice ci-dessous)
  - Dispatche aux workers appropriés
  - Peut annuler des workers en cours si nécessaire
- [ ] **Matrice de décision** :
  ```
  | Event           | En cours         | Action                              |
  |-----------------|------------------|-------------------------------------|
  | LOCAL_MODIFIED  | DOWNLOAD même    | Annuler download, attendre, upload  |
  | REMOTE_MODIFIED | UPLOAD même      | Marquer conflit potentiel           |
  | LOCAL_DELETED   | DOWNLOAD même    | Annuler download, propager delete   |
  | REMOTE_DELETED  | UPLOAD même      | Créer conflict-copy, continuer      |
  | LOCAL_MODIFIED  | Aucun            | Ajouter upload à la queue           |
  | REMOTE_MODIFIED | Aucun            | Ajouter download à la queue         |
  ```
- [ ] **Transfer tracking** : Suivi des transferts en cours (path → worker)

### 15.3 - Workers Interruptibles

- [ ] **BaseWorker class** : Worker de base avec support annulation
  - Threading ou asyncio
  - Méthode `cancel()` pour arrêt propre
  - Callback `on_complete`, `on_error`, `on_cancelled`
- [ ] **UploadWorker** : Refactor de FileUploader en worker
  - Vérifie régulièrement le flag cancelled
  - Peut reprendre (chunk-level resume existant)
- [ ] **DownloadWorker** : Refactor de FileDownloader en worker
  - Écriture atomique (.tmp → rename) existante
  - Support annulation mid-download
- [ ] **Worker Pool** : Pool de N workers concurrents (configurable)

### 15.4 - WebSocket Bidirectionnel

#### Server → Client (notifications de changements)
- [ ] **Endpoint `/ws/changes`** : Notifie les clients des modifications fichiers
  - Event format : `{"type": "file_changed", "path": "...", "version": N}`
  - Authentification par token
- [ ] **Client listener** : Connexion persistante, reconnexion auto avec backoff
- [ ] **Injection events** : REMOTE_* events injectés dans la queue locale

#### Client → Server (reporting de progression)
- [ ] **Endpoint `/ws/events`** : Reçoit les events des clients
- [ ] **Events émis** :
  - `sync_started` (machine_id, file_count)
  - `sync_progress` (machine_id, file_path, current_chunk, total_chunks, bytes)
  - `sync_completed` (machine_id, files_uploaded, files_downloaded)
  - `sync_error` (machine_id, error_message)
  - `conflict_detected` (machine_id, file_path, local_version, server_version)
- [ ] **File d'attente locale** : Buffer si déconnecté, replay on reconnect

### 15.5 - Server WebSocket Hub

- [ ] **Endpoint `/ws/dashboard`** : Pour le browser (WebUI)
- [ ] **Hub central** : Relaie events clients → browsers
- [ ] **État en mémoire** : Status courant de chaque machine
- [ ] **API REST fallback** : `/api/machines/{id}/status` pour polling

### 15.6 - Dashboard WebUI Real-Time

- [ ] **Connexion WebSocket** depuis le browser vers `/ws/dashboard`
- [ ] **Page "Activity"** :
  - Live Sync Progress : Barres de progression par machine/fichier
  - Transfer Queue : Fichiers en cours de transfert (toutes machines)
  - Activity Log : Stream temps réel des événements
- [ ] **Page "Machines" enrichie** :
  - Status live (syncing, idle, error, offline)
  - Dernier fichier synchronisé
  - Vitesse de transfert
- [ ] **Tray Icon** : Clic gauche → ouvre dashboard

### 15.7 - Conflict Resolution Améliorée

- [ ] **Détection précoce** : Détecter conflit AVANT de terminer le transfert
- [ ] **Versioning in-flight** : Savoir quelle version est en cours de transfert

### Tests & Qualité

- [ ] Tests unitaires EventQueue, Coordinator, Workers
- [ ] Tests unitaires WebSocket hub
- [ ] Tests intégration : Scénarios de conflit mid-transfer
- [ ] Tests de charge : 1000+ events dans la queue
- [ ] Mypy strict + Ruff zero warnings

### Priorité d'Implémentation

1. **EventQueue + Event types** (fondation)
2. **Coordinator basique** (décisions sans workers)
3. **Workers interruptibles** (refactor upload/download)
4. **WebSocket Server→Client** (notifications)
5. **WebSocket Client→Server** (reporting)
6. **WebSocket Hub + Dashboard**

**Fichiers à créer/modifier:**
- Client:
  - `src/syncagent/client/sync/queue.py` (nouveau)
  - `src/syncagent/client/sync/coordinator.py` (nouveau)
  - `src/syncagent/client/sync/workers.py` (nouveau)
  - `src/syncagent/client/websocket.py` (nouveau)
  - `src/syncagent/client/sync/engine.py` (refactor)
- Server:
  - `src/syncagent/server/websocket.py` (nouveau)
  - `src/syncagent/server/web/templates/activity.html` (nouveau)

**Dépendances:** `websockets` (déjà présent)

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

---

## Analyse des Écarts - Architecture de Synchronisation (ChatGPT Discussion Dec 2024)

### Contexte

Discussion avec ChatGPT sur l'architecture optimale pour un système de synchronisation bidirectionnelle réactive, inspirée des solutions state-of-the-art comme Dropbox, Syncthing, Google Drive et OneDrive.

### État Actuel vs Attentes

| Composant | État Actuel | Attendu (State of the Art) |
|-----------|-------------|----------------------------|
| **Watcher local** | ✅ watchdog + debouncing (250ms + 3s delay) | ✅ OK |
| **Queue d'événements** | ❌ Pas de queue - traitement synchrone direct | File d'attente locale pour coordonner les actions |
| **Coordinator/Orchestrateur** | ❌ SyncEngine fait push/pull séquentiellement | Coordinator central gérant les priorités et conflits |
| **Notifications serveur (push)** | ❌ Pas de WebSocket - scan périodique uniquement | WebSocket pour notifications temps réel du serveur |
| **Workers background** | ❌ Uploads/downloads bloquants dans le thread principal | Threads/tâches interruptibles contrôlés par le coordinator |
| **Gestion mid-transfer** | ❌ Pas de gestion si fichier modifié pendant transfert | Pause/reprise automatique si fichier change en cours de transfert |
| **Matrice de scénarios** | Partiel (hash identique = auto-resolve, sinon conflict copy) | Matrice complète de tous les cas possibles |

### Scénarios Non Couverts

Les scénarios suivants ne sont pas explicitement gérés dans l'architecture actuelle :

1. **Fichier modifié localement pendant un download** - Le download écrase potentiellement la modification locale
2. **Fichier modifié côté serveur pendant un upload** - Détecté comme conflit après coup, pas pendant
3. **Modification simultanée des deux côtés** - Géré par conflit mais pas de notification temps réel
4. **Upload/download interrompu par modification** - Pas de mécanisme pour stopper et relancer avec nouvelle version
5. **Fichier supprimé d'un côté, modifié de l'autre** - Cas edge non documenté

### Référence State of the Art

#### Dropbox (d'après documentation technique)
- **Composants client** : Watcher, Chunker, Indexer, Internal DB
- **Message Queue** :
  - Request Queue globale (clients → Synchronization Service)
  - Response Queue par client (broadcast des updates)
- **Synchronization Service** : Traite les updates et notifie les clients abonnés
- **Conflits** : Création de "conflicted_copy" avec dernier écrivain gagne

Sources :
- [Dropbox System Design](https://www.systemdesignhandbook.com/guides/dropbox-system-design-interview/)
- [How Dropbox Handles Conflicts](https://dropbox.tech/developers/how-the-dropbox-datastore-api-handles-conflicts-part-two-resolving-collisions)

#### Syncthing (d'après documentation)
- **Model central** : Orchestrateur de toutes les activités de synchronisation
- **Event subsystem** : Pub/sub pour événements inter-composants
- **Routines concurrentes** : pullerRoutine, copierRoutine, finisherRoutine, dbUpdaterRoutine
- **Index exchange** : Comparaison d'état entre devices

Sources :
- [Syncthing Architecture](https://delftswa.gitbooks.io/desosa-2017/content/syncthing/chapter.html)
- [Syncthing Synchronization Model](https://deepwiki.com/syncthing/syncthing/2.2-synchronization-model)

#### Patterns Généraux Event-Driven
- **Event Queue Pattern** : Gestion asynchrone des tâches
- **Work Queue** : Distribution du travail entre workers concurrents
- **Fan-out** : Propagation d'un événement vers plusieurs destinations
- **Dead Letter Queue** : Gestion des erreurs
- **Outbox Pattern** : Consistance entre DB et publication d'événements
- **Backpressure** : Gestion de la charge

Sources :
- [Event Queue Pattern in Java](https://java-design-patterns.com/patterns/event-queue/)
- [Event-Driven Architecture Patterns](https://solace.com/event-driven-architecture-patterns/)

---

