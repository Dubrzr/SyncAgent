# File Sync - Zero Knowledge E2EE

Synchronisation de fichiers entre 3-4 machines (Windows/macOS/Linux) avec chiffrement côté client et stockage de blocs chiffrés sur block storage externe.

## Contexte
- **Machines:** 3-4 (Windows, macOS, Linux)
- **Usage:** Modifications simultanées fréquentes sur plusieurs machines
- **Fichiers:** Tailles très variables (petits docs → gros fichiers)
- **Sécurité:** Zero-Knowledge - le serveur ne voit JAMAIS les données en clair
- **Transport:** HTTPS (plus besoin de SSH car E2EE)

---

## Requirements Fonctionnels

### R1. Synchronisation
- [ ] Sync bidirectionnel entre machines (via serveur)
- [ ] Détection automatique des changements locaux (file watcher + scan backup 5min)
- [ ] Sync incrémental (ne pas re-uploader les fichiers inchangés)
- [ ] Content-Defined Chunking (CDC) pour delta sync optimisé (insertions/modifications)
- [ ] Support fichiers de toutes tailles
- [ ] Debounce events : 250ms (coalescing multiple events)
- [ ] Délai avant sync : 3s après dernière modification
- [ ] Sync initiale : dossier local DOIT être vide (download complet du remote)
- [ ] Détection des renommages via hash des blocs (pas de retransmission)
- [ ] Paths/noms de fichiers NON chiffrés (permet recherche dans Web UI)
- [ ] Streaming : lecture/écriture chunk par chunk (max 8 MB en RAM)
- [ ] Resume après interruption : reprend à partir des chunks manquants
- [ ] Intégrité : hash SHA-256 vérifié à chaque chunk (upload et download)

### R2. Chiffrement (E2EE)
- [ ] Chiffrement côté client uniquement
- [ ] Serveur ne voit jamais les données en clair
- [ ] Clé dérivée d'un mot de passe maître
- [ ] Partage de clé entre machines (export/import)
- [ ] Algorithme robuste (AES-GCM ou ChaCha20)

### R3. Gestion des conflits
- [ ] Détection automatique des conflits
- [ ] Stratégie : duplication des fichiers conflictuels
- [ ] Nommage clair : `fichier (conflit - machine).ext`
- [ ] Résolution manuelle par l'utilisateur

### R4. Stockage
- [ ] Block storage externe (S3-compatible)
- [ ] Mode local FS pour dev/test
- [ ] Chunks liés exclusivement à leur fichier (pas de déduplication v1)
- [ ] Suppression des chunks à la purge de corbeille (simple, pas de GC complexe)
- [ ] Note : Déduplication inter-fichiers prévue ultérieurement (v2)

### R4bis. Corbeille (fichiers supprimés)
- [ ] Fichiers supprimés conservés X jours (configurable, défaut 30j)
- [ ] Page dédiée dans Web UI pour consulter la corbeille
- [ ] Restauration possible depuis Web UI
- [ ] Purge automatique après expiration
- [ ] Note : système de backup complet prévu ultérieurement

### R5. Client local
- [ ] Daemon en arrière-plan
- [ ] File watcher (détection changements)
- [ ] Tray icon avec statut
- [ ] CLI pour configuration et debug
- [ ] Protocol handler (`syncfile://`) pour ouvrir fichiers depuis Web UI
- [ ] Cross-platform (Windows, macOS, Linux)

### R6. Serveur
- [ ] API REST pour métadonnées
- [ ] Stockage métadonnées uniquement (Zero Knowledge)
- [ ] Pas d'historique de versions (dernière version uniquement pour économie stockage)
- [ ] Détection et signalement des conflits
- [ ] Note : backup complet prévu ultérieurement (indépendant du versioning)

### R7. Web UI
- [ ] File browser (métadonnées seulement)
- [ ] Recherche par nom de fichier/dossier
- [ ] Vue des conflits
- [ ] Statut des machines
- [ ] Page Corbeille (fichiers supprimés) avec restauration
- [ ] Responsive (mobile-friendly)

### R8. Authentification
- [ ] Auth machines : token Bearer
- [ ] Auth Web UI : session cookie (HttpOnly, Secure, SameSite=Strict)
- [ ] Tokens stockés hashés côté serveur
- [ ] Compte admin unique créé via setup wizard (première visite Web UI)
- [ ] Mot de passe admin : minimum 14 caractères
- [ ] Protection CSRF (token dans formulaires)
- [ ] Session expiration : 24h (configurable)
- [ ] Note : Rate limiting géré en amont (nginx/reverse proxy)

### R9. Sync temps réel (WebSocket client ↔ serveur)
- [ ] Connexion WebSocket permanente du daemon client au serveur
- [ ] Push notification quand un autre client upload un fichier
- [ ] Sync quasi-instantanée entre machines (< 5s)
- [ ] Reconnexion automatique avec backoff exponentiel
- [ ] Heartbeat pour détecter déconnexions
- [ ] Note : Web UI sans WebSocket (refresh manuel suffit)

### R10. Enregistrement machines
- [ ] Nom unique par machine
- [ ] Validation format nom (alphanum, tirets, underscores)
- [ ] Génération token à l'enregistrement
- [ ] Workflow première machine vs machines suivantes
- [ ] Invitation token (usage unique, expire en 24h)
- [ ] Génération des invitations via Web UI uniquement
- [ ] Admin peut voir/révoquer les invitations en attente

### R11. Gestion du master password
- [ ] Dérivation clé via Argon2id (résistant brute-force)
- [ ] Deux clés : master_key (dérivée) + encryption_key (aléatoire)
- [ ] Changement de password sans re-chiffrer les fichiers
- [ ] Stockage clé : keyring OS par défaut (Windows Credential Manager / macOS Keychain / Linux Secret Service)
- [ ] Mode "prompt" optionnel (demande password à chaque démarrage)
- [ ] Commandes : `unlock`, `lock`, `change-password`

---

## Requirements Non-Fonctionnels

### R12. Qualité du code (niveau senior)
- [ ] Code coverage ≥ 95% pour le client (hors tray icon)
- [ ] Code coverage ≥ 95% pour le serveur (hors templates Web UI)
- [ ] Tests d'intégration client ↔ serveur
- [ ] Linting : ruff (zero warnings)
- [ ] Type checking : mypy strict
- [ ] Commits fréquents respectant [Conventional Commits](https://www.conventionalcommits.org/)
  - `feat:` nouvelle fonctionnalité
  - `fix:` correction de bug
  - `refactor:` refactoring sans changement fonctionnel
  - `test:` ajout/modification de tests
  - `docs:` documentation
  - `chore:` maintenance (deps, config, CI)

### R13. Best practices (niveau senior)
- [ ] SOLID principles
- [ ] DRY (Don't Repeat Yourself)
- [ ] Separation of concerns (couches distinctes : API, business logic, data)
- [ ] Dependency injection pour testabilité
- [ ] Configuration externalisée (pas de hardcoding)
- [ ] Logging structuré avec niveaux (DEBUG, INFO, WARNING, ERROR)
- [ ] Gestion d'erreurs explicite (pas de `except: pass`)
- [ ] Docstrings pour les fonctions publiques
- [ ] Code auto-documenté (noms explicites, pas de magic numbers)
- [ ] Tests : unitaires, intégration, et edge cases
- [ ] Revue de code avant merge (si applicable)

---

## 1. Architecture Zero-Knowledge

```
┌─────────────────────────────────────────────────────────────────┐
│                         BLOCK STORAGE                           │
│                     (OVH S3 / Swift / Ceph)                     │
├─────────────────────────────────────────────────────────────────┤
│  Blocs chiffrés uniquement - illisibles sans clé client         │
│  /{user_id}/{chunk_hash}.enc                                    │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTPS (blocs chiffrés)
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                      SERVEUR MÉTADONNÉES                        │
│                    (FastAPI + SQLite WAL)                       │
├─────────────────────────────────────────────────────────────────┤
│  NE STOCKE QUE :                                                │
│  - Arborescence des fichiers                                    │
│  - Hash des blocs (pas le contenu)                              │
│  - Versions et branches                                         │
│  - Conflits détectés                                            │
│  - Métadonnées machines                                         │
│                                                                 │
│  NE VOIT JAMAIS :                                               │
│  - Le contenu des fichiers                                      │
│  - Les clés de chiffrement                                      │
│  - Les blocs déchiffrés                                         │
└─────────────────────────────────────────────────────────────────┘
                              ▲
                              │ HTTPS (métadonnées + blocs chiffrés)
                              │
┌─────────────────────────────┴───────────────────────────────────┐
│                       CLIENT LOCAL                              │
├─────────────────────────────────────────────────────────────────┤
│  SEUL ENDROIT OÙ :                                              │
│  - Les fichiers sont en clair                                   │
│  - Le chiffrement/déchiffrement a lieu                          │
│  - La clé E2EE existe                                           │
│                                                                 │
│  Composants :                                                   │
│  - File watcher (watchdog)                                      │
│  - Moteur de chiffrement (AES-GCM)                              │
│  - Content-Defined Chunking (CDC)                               │
│  - SQLite local                                                 │
│  - Tray icon (pystray)                                          │
│  - Protocol handler (syncfile://)                               │
└─────────────────────────────────────────────────────────────────┘
```

---

## 2. Modèle de Sécurité

### 2.1 Séparation des clés
```
┌─────────────────┐     ┌─────────────────┐
│   Token Auth    │     │    Clé E2EE     │
│   (HTTPS API)   │     │   (locale)      │
├─────────────────┤     ├─────────────────┤
│ Authentifie     │     │ Chiffre les     │
│ le client       │     │ données         │
│                 │     │                 │
│ Permet :        │     │ Permet :        │
│ - Upload blocs  │     │ - Lire fichiers │
│ - Modifier meta │     │ - Écrire        │
│ - Supprimer     │     │   fichiers      │
└─────────────────┘     └─────────────────┘

Vol du token seul    → Accès aux blocs CHIFFRÉS (inutiles)
Vol de la clé seule  → Impossible d'accéder au serveur
Vol des deux         → Compromission (mais nécessite accès physique)
Hack du serveur      → RIEN (Zero Knowledge)
Hack du storage OVH  → RIEN (blocs chiffrés)
```

### 2.2 Chiffrement des blocs
```python
# Algorithme : AES-256-GCM (ou ChaCha20-Poly1305)
# Dérivation : Argon2id depuis master password

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os

CHUNK_SIZE = 4 * 1024 * 1024  # 4 MB

def derive_key(master_password: str, salt: bytes) -> bytes:
    """Dérive une clé 256-bit depuis le mot de passe"""
    from argon2.low_level import hash_secret_raw, Type
    return hash_secret_raw(
        secret=master_password.encode(),
        salt=salt,
        time_cost=3,
        memory_cost=65536,
        parallelism=4,
        hash_len=32,
        type=Type.ID
    )

def encrypt_chunk(data: bytes, key: bytes) -> bytes:
    """Chiffre un bloc avec nonce unique"""
    nonce = os.urandom(12)  # 96 bits pour AES-GCM
    aesgcm = AESGCM(key)
    ciphertext = aesgcm.encrypt(nonce, data, None)
    return nonce + ciphertext  # Préfixe le nonce

def decrypt_chunk(encrypted: bytes, key: bytes) -> bytes:
    """Déchiffre un bloc"""
    nonce = encrypted[:12]
    ciphertext = encrypted[12:]
    aesgcm = AESGCM(key)
    return aesgcm.decrypt(nonce, ciphertext, None)
```

### 2.3 Stockage de la clé locale
```json
// ~/.syncagent/keyfile.json (chiffré par mot de passe OS ou master password)
{
  "salt": "base64...",
  "encrypted_master_key": "base64...",
  "key_id": "uuid",
  "created_at": "2025-01-01T00:00:00Z"
}
```

---

## 3. Serveur Métadonnées

### 3.1 Ce que le serveur stocke
```sql
-- Fichiers (métadonnées uniquement)
CREATE TABLE files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,       -- Chemin relatif UNIQUE (NON chiffré pour recherche)
    is_directory BOOLEAN DEFAULT FALSE,  -- TRUE pour dossiers vides
    current_version_id TEXT,         -- NULL pour dossiers vides
    created_at REAL,
    updated_at REAL,
    is_deleted BOOLEAN DEFAULT FALSE,
    deleted_at REAL,                 -- Timestamp suppression (pour corbeille 30j)
    deleted_by_machine_id TEXT       -- Machine ayant supprimé
);

-- Versions (branches)
CREATE TABLE versions (
    id TEXT PRIMARY KEY,             -- UUID
    file_id INTEGER,
    machine_id TEXT,
    chunk_hashes TEXT,               -- JSON: ["hash1", "hash2", ...]
    size INTEGER,
    mtime REAL,
    created_at REAL,
    parent_version_id TEXT,          -- Pour l'historique
    FOREIGN KEY (file_id) REFERENCES files(id)
);

-- Conflits détectés
CREATE TABLE conflicts (
    id INTEGER PRIMARY KEY,
    file_id INTEGER,
    detected_at REAL,
    branches TEXT,                   -- JSON: [{"machine": "laptop", "version_id": "..."}]
    resolved BOOLEAN DEFAULT FALSE,
    FOREIGN KEY (file_id) REFERENCES files(id)
);

-- Machines enregistrées
CREATE TABLE machines (
    machine_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,
    os TEXT,
    token_hash TEXT NOT NULL,
    created_at REAL,
    last_seen REAL,
    is_active BOOLEAN DEFAULT TRUE
);

-- Invitations (tokens à usage unique)
CREATE TABLE invitations (
    token_hash TEXT PRIMARY KEY,
    created_at REAL,
    expires_at REAL,              -- created_at + 24h
    used_by_machine_id TEXT,      -- NULL si pas encore utilisé
    used_at REAL
);

-- Admin unique (un seul enregistrement possible)
CREATE TABLE admin (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    username TEXT NOT NULL,
    password_hash TEXT NOT NULL,  -- Argon2id
    created_at REAL
);

-- Sessions admin (Web UI)
CREATE TABLE sessions (
    token_hash TEXT PRIMARY KEY,
    created_at REAL,
    expires_at REAL,              -- created_at + 24h (configurable)
    user_agent TEXT,
    ip_address TEXT
);
-- Nettoyage automatique des sessions expirées via background job

-- Mapping blocs → storage (sans déduplication inter-fichiers v1)
CREATE TABLE chunks (
    hash TEXT PRIMARY KEY,
    file_id INTEGER NOT NULL,        -- Fichier propriétaire (pas de dédup)
    storage_path TEXT,               -- Chemin dans OVH
    size INTEGER,
    uploaded_at REAL,
    FOREIGN KEY (file_id) REFERENCES files(id)
);
-- Note v1 : Chaque fichier possède ses propres chunks.
-- Suppression directe des chunks à la purge de corbeille.
-- Déduplication inter-fichiers prévue en v2 (ref_count, GC avec grace period).

-- Configuration serveur
CREATE TABLE config (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Valeurs par défaut:
-- trash_retention_days: 30
```

### 3.2 API HTTPS

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/auth/register` | Enregistre une machine (token retourné à la création) |
| `GET` | `/api/files` | Liste les fichiers (métadonnées) |
| `GET` | `/api/files/{id}/versions` | Versions d'un fichier |
| `POST` | `/api/files` | Crée/modifie un fichier (metadata) |
| `DELETE` | `/api/files/{id}` | Supprime (tombstone) |
| `GET` | `/api/chunks/{hash}` | Télécharge un bloc chiffré |
| `POST` | `/api/chunks` | Upload un bloc chiffré |
| `HEAD` | `/api/chunks/{hash}` | Vérifie si bloc existe |
| `GET` | `/api/conflicts` | Liste les conflits |
| `POST` | `/api/conflicts/{id}/resolve` | Résout un conflit |
| `GET` | `/api/status` | État des machines |
| `GET` | `/api/changes?since=<ts>` | Changements depuis timestamp (catch-up) |
| `POST` | `/api/auth/check-name` | Vérifie disponibilité nom machine |
| `GET` | `/api/trash` | Liste fichiers supprimés (corbeille) |
| `POST` | `/api/trash/{id}/restore` | Restaure un fichier |
| `DELETE` | `/api/trash/{id}` | Supprime définitivement |
| `GET` | `/api/invitations` | Liste invitations (admin) |
| `POST` | `/api/invitations` | Crée une invitation (admin) |
| `DELETE` | `/api/invitations/{id}` | Révoque une invitation (admin) |

### 3.3 Setup Wizard (première visite Web UI)

À la première connexion sur la Web UI, si aucun admin n'existe, l'utilisateur est redirigé vers un écran de setup :

```
┌─────────────────────────────────────────────────────────────────┐
│                     SyncAgent - Setup                           │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Bienvenue ! Créez votre compte administrateur.                 │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ Nom d'utilisateur                                       │    │
│  │ ┌─────────────────────────────────────────────────────┐ │    │
│  │ │ admin                                               │ │    │
│  │ └─────────────────────────────────────────────────────┘ │    │
│  │                                                         │    │
│  │ Mot de passe                                            │    │
│  │ ┌─────────────────────────────────────────────────────┐ │    │
│  │ │ ••••••••••••                                        │ │    │
│  │ └─────────────────────────────────────────────────────┘ │    │
│  │                                                         │    │
│  │ Confirmer le mot de passe                               │    │
│  │ ┌─────────────────────────────────────────────────────┐ │    │
│  │ │ ••••••••••••                                        │ │    │
│  │ └─────────────────────────────────────────────────────┘ │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│                              [Créer le compte]                  │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

```python
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse

def needs_setup(db) -> bool:
    """Vérifie si le setup initial est nécessaire"""
    return db.execute("SELECT 1 FROM admin WHERE id = 1").fetchone() is None

@app.middleware("http")
async def setup_redirect(request: Request, call_next):
    """Redirige vers /setup si pas d'admin configuré"""
    if needs_setup(db):
        # Autoriser uniquement /setup et ses assets
        if not request.url.path.startswith(("/setup", "/static")):
            return RedirectResponse(url="/setup")
    else:
        # Setup déjà fait, bloquer l'accès à /setup
        if request.url.path.startswith("/setup"):
            return RedirectResponse(url="/")
    return await call_next(request)

@app.get("/setup")
def setup_page():
    """Page de création du compte admin"""
    if not needs_setup(db):
        return RedirectResponse(url="/")
    return templates.TemplateResponse("setup.html", {})

@app.post("/setup")
def create_admin(username: str, password: str, password_confirm: str):
    """Crée le compte admin"""
    if not needs_setup(db):
        return RedirectResponse(url="/")

    if password != password_confirm:
        return {"error": "Les mots de passe ne correspondent pas"}

    if len(password) < 14:
        return {"error": "Mot de passe trop court (min 14 caractères)"}

    ph = PasswordHasher()
    db.execute("""
        INSERT INTO admin (id, username, password_hash, created_at)
        VALUES (1, ?, ?, ?)
    """, (username, ph.hash(password), time.time()))
    db.commit()

    return RedirectResponse(url="/login")
```

### 3.4 Web UI (FastAPI + Jinja2 + HTMX)
- **Affiche uniquement les métadonnées** (noms, tailles, dates, conflits)
- **Ne peut PAS afficher le contenu** des fichiers (Zero Knowledge)
- **Lien vers client local** via `syncfile://` pour ouvrir les fichiers

```html
<!-- Le front ne voit que ça -->
<tr>
  <td>
    <a href="syncfile://open?path=/docs/rapport.pdf">
      rapport.pdf
    </a>
  </td>
  <td>2.4 MB</td>
  <td>2025-01-15 14:30</td>
  <td>laptop</td>
</tr>
```

### 3.5 Workflow initial (Setup → Première machine)

```
1. SERVEUR
   - Démarrage serveur (premier lancement)
   - DB vide, pas d'admin

2. ADMIN (Web UI)
   - Accès https://sync.mondomaine.com
   - Redirection auto vers /setup (pas d'admin)
   - Création compte admin (username + password 14+ chars)
   - Connexion Web UI avec session cookie

3. INVITATION (Web UI)
   - Admin génère un token d'invitation
   - Token affiché : INV-xxxxxxxxxxxx (expire 24h)
   - Admin copie le token

4. PREMIÈRE MACHINE (CLI)
   - syncagent init
   - Saisie URL serveur, token invitation, nom machine
   - Génération clé E2EE (première machine)
   - POST /api/auth/register → token machine
   - Export clé : syncagent export-key > ma-cle.key

5. MACHINES SUIVANTES (CLI)
   - Admin génère nouvelle invitation (Web UI)
   - syncagent init --import-key ma-cle.key
   - Saisie URL, invitation, nom
   - Import clé E2EE (même clé que première machine)
   - POST /api/auth/register → nouveau token machine
```

### 3.6 Background Jobs (serveur)

Le serveur exécute des tâches de maintenance périodiques :

```python
import asyncio
from datetime import datetime, timedelta

async def background_jobs():
    """Tâches de maintenance exécutées en arrière-plan"""
    while True:
        await asyncio.gather(
            purge_expired_trash(),
            cleanup_expired_sessions(),
            cleanup_expired_invitations(),
        )
        await asyncio.sleep(3600)  # Toutes les heures

async def purge_expired_trash():
    """Purge les fichiers en corbeille expirés et leurs chunks"""
    retention = get_config('trash_retention_days', 30)
    cutoff = time.time() - (retention * 86400)

    expired = db.execute("""
        SELECT id FROM files
        WHERE is_deleted = TRUE AND deleted_at < ?
    """, (cutoff,)).fetchall()

    for file in expired:
        # Supprimer les chunks associés
        await storage.delete_by_file(file['id'])
        # Supprimer le fichier de la DB
        db.execute("DELETE FROM files WHERE id = ?", (file['id'],))

    db.commit()
    logger.info(f"Purged {len(expired)} expired files from trash")

async def cleanup_expired_sessions():
    """Nettoie les sessions admin expirées"""
    db.execute("DELETE FROM sessions WHERE expires_at < ?", (time.time(),))
    db.commit()

async def cleanup_expired_invitations():
    """Nettoie les invitations expirées non utilisées"""
    db.execute("""
        DELETE FROM invitations
        WHERE expires_at < ? AND used_by_machine_id IS NULL
    """, (time.time(),))
    db.commit()
```

### 3.7 Détection machine offline (WebSocket)

```python
# Configuration
WS_HEARTBEAT_INTERVAL = 30  # Client envoie ping toutes les 30s (configurable)
WS_TIMEOUT = 90             # Serveur ferme si pas de ping depuis 90s (3x interval)

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # ... authentification ...

    await websocket.accept()
    active_connections[machine.machine_id] = websocket

    # Mettre à jour last_seen et notifier les autres
    update_machine_last_seen(machine.machine_id)
    await broadcast_to_others(machine.machine_id, {
        "type": "machine_online",
        "machine_id": machine.machine_id,
        "name": machine.name
    })

    try:
        while True:
            # Timeout si pas de message depuis WS_TIMEOUT secondes
            data = await asyncio.wait_for(
                websocket.receive_json(),
                timeout=WS_TIMEOUT
            )
            if data.get("type") == "ping":
                update_machine_last_seen(machine.machine_id)
                await websocket.send_json({"type": "pong"})
    except (WebSocketDisconnect, asyncio.TimeoutError):
        del active_connections[machine.machine_id]
        await broadcast_to_others(machine.machine_id, {
            "type": "machine_offline",
            "machine_id": machine.machine_id,
            "name": machine.name
        })
```

### 3.8 Gestion des erreurs chunks (404)

```python
# Client : gestion du 404 lors du download
async def download_chunk_safe(chunk_hash: str) -> bytes | None:
    """Télécharge un chunk avec gestion du 404"""
    try:
        response = await httpx.get(f"{server_url}/api/chunks/{chunk_hash}")
        if response.status_code == 404:
            # Chunk supprimé (fichier purgé de corbeille pendant le download)
            logger.warning(f"Chunk {chunk_hash} not found (deleted)")
            return None
        response.raise_for_status()
        return response.content
    except httpx.HTTPStatusError as e:
        logger.error(f"Failed to download chunk {chunk_hash}: {e}")
        raise

async def download_file_safe(file_id: str, version_id: str, local_path: str) -> bool:
    """Download avec retry si 404 sur chunk"""
    metadata = await api.get_version(file_id, version_id)

    # Si le fichier a été purgé entre-temps, ses chunks n'existent plus
    if metadata.get('is_deleted') and metadata.get('deleted_at'):
        if time.time() - metadata['deleted_at'] > (30 * 86400):  # > 30 jours
            logger.warning(f"File {file_id} was purged, skipping download")
            return False

    with open(local_path, 'wb') as f:
        for chunk_hash in metadata['chunk_hashes']:
            chunk_data = await download_chunk_safe(chunk_hash)
            if chunk_data is None:
                # Chunk manquant → fichier incomplet
                logger.error(f"Missing chunk {chunk_hash}, aborting download")
                return False
            decrypted = decrypt_chunk(chunk_data, e2ee_key)
            f.write(decrypted)

    return True
```

---

## 4. Client Local

### 4.1 Enregistrement d'un nouveau client

#### Processus d'initialisation
```
┌─────────────────────────────────────────────────────────────────┐
│                    syncagent init                               │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  1. Demande l'URL du serveur                                    │
│     > URL du serveur: https://sync.mondomaine.com               │
│                                                                 │
│  2. Demande le token d'invitation (généré via Web UI)           │
│     > Token d'invitation: INV-a8f3b2c9d4e5f6a7                  │
│                                                                 │
│  3. Demande le nom de la machine                                │
│     > Nom de cette machine: laptop-julien                       │
│                                                                 │
│  4. Demande le dossier local à synchroniser                     │
│     > Dossier à synchroniser: ~/Sync                            │
│                                                                 │
│  5. Première machine ? → Génère la clé E2EE                     │
│     Machine existante ? → Importe la clé E2EE                   │
│     > Mot de passe maître: ********                             │
│                                                                 │
│  6. Enregistre la machine sur le serveur                        │
│     POST /api/auth/register                                     │
│     {                                                           │
│       "invite_token": "INV-a8f3b2c9d4e5f6a7",                   │
│       "name": "laptop-julien",                                  │
│       "os": "windows"                                           │
│     }                                                           │
│     → 201 Created {"machine_id": "uuid...", "token": "..."}     │
│     → Token d'invitation consommé (usage unique)                │
│                                                                 │
│  7. Sauvegarde la config locale                                 │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

#### Génération d'invitation (Web UI)
```
┌─────────────────────────────────────────────────────────────────┐
│                    WEB UI - Machines                            │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  Machines connectées:                                           │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ 🟢 laptop-julien    Windows   Dernière sync: il y a 2m  │    │
│  │ 🟢 desktop-bureau   Linux     Dernière sync: il y a 5m  │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  [+ Inviter une machine]                                        │
│                                                                 │
│  ─────────────────────────────────────────────────────────────  │
│                                                                 │
│  Invitations en attente:                                        │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │ INV-a8f3...  Créée il y a 2h   Expire dans 22h  [🗑️]   │    │
│  │ INV-b7c2...  Créée il y a 1j   EXPIRÉ           [🗑️]   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘

Clic sur [+ Inviter une machine]:
┌─────────────────────────────────────────────────────────────────┐
│                                                                 │
│  Token d'invitation généré :                                    │
│                                                                 │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │  INV-a8f3b2c9d4e5f6a7                        [Copier]   │    │
│  └─────────────────────────────────────────────────────────┘    │
│                                                                 │
│  ⚠️ Ce token expire dans 24h et ne peut être utilisé qu'une    │
│     seule fois.                                                 │
│                                                                 │
│  Commande à exécuter sur la nouvelle machine :                  │
│  $ syncagent init                                               │
│                                                                 │
│                                              [Fermer]           │
└─────────────────────────────────────────────────────────────────┘
```

#### Contraintes sur le nom de machine
- **Unique** sur le serveur (vérifié à l'enregistrement)
- **Format:** lettres, chiffres, tirets, underscores
- **Longueur:** 3-32 caractères
- **Pas de caractères spéciaux** (sera utilisé dans les noms de fichiers conflits)

```python
import re

def validate_machine_name(name: str) -> bool:
    """Valide le format du nom de machine"""
    pattern = r'^[a-zA-Z0-9_-]{3,32}$'
    return bool(re.match(pattern, name))

# Exemples valides:
# - laptop-julien
# - desktop_bureau
# - macbook-pro-2024
# - PC01

# Exemples invalides:
# - "mon pc" (espaces)
# - "laptop@home" (caractère spécial)
# - "ab" (trop court)
```

#### API d'enregistrement (serveur)
```python
@app.post("/api/auth/check-name")
def check_name():
    """Vérifie si un nom de machine est disponible"""
    name = request.json['name']

    if not validate_machine_name(name):
        return {"error": "Invalid name format"}, 400

    exists = db.execute(
        "SELECT 1 FROM machines WHERE name = ?", (name,)
    ).fetchone()

    if exists:
        return {"error": "Name already taken"}, 409

    return {"available": True}, 200


@app.post("/api/auth/register")
def register_machine():
    """Enregistre une nouvelle machine avec validation du token d'invitation"""
    data = request.json
    name = data['name']
    os_type = data['os']
    invite_token = data.get('invite_token')

    # 1. Valider le token d'invitation
    if not invite_token:
        return {"error": "Invitation token required"}, 401

    invite_hash = hashlib.sha256(invite_token.encode()).hexdigest()
    invitation = db.execute("""
        SELECT token_hash, expires_at, used_by_machine_id
        FROM invitations
        WHERE token_hash = ?
    """, (invite_hash,)).fetchone()

    if not invitation:
        return {"error": "Invalid invitation token"}, 401

    if invitation['used_by_machine_id']:
        return {"error": "Invitation token already used"}, 401

    if invitation['expires_at'] < time.time():
        return {"error": "Invitation token expired"}, 401

    # 2. Valider le nom de machine
    if not validate_machine_name(name):
        return {"error": "Invalid name format"}, 400

    exists = db.execute(
        "SELECT 1 FROM machines WHERE name = ?", (name,)
    ).fetchone()
    if exists:
        return {"error": "Name already taken"}, 409

    # 3. Créer la machine
    machine_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    token_hash = hashlib.sha256(token.encode()).hexdigest()

    db.execute("""
        INSERT INTO machines (machine_id, name, os, token_hash, created_at, last_seen)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (machine_id, name, os_type, token_hash, time.time(), time.time()))

    # 4. Marquer l'invitation comme utilisée
    db.execute("""
        UPDATE invitations
        SET used_by_machine_id = ?, used_at = ?
        WHERE token_hash = ?
    """, (machine_id, time.time(), invite_hash))

    db.commit()

    return {
        "machine_id": machine_id,
        "token": token  # Renvoyé une seule fois !
    }, 201
```

#### Schéma DB machines (mis à jour)
```sql
CREATE TABLE machines (
    machine_id TEXT PRIMARY KEY,
    name TEXT UNIQUE NOT NULL,       -- Nom unique choisi par l'utilisateur
    os TEXT,                         -- windows, darwin, linux
    token_hash TEXT NOT NULL,        -- Hash du token (jamais le token en clair)
    created_at REAL,
    last_seen REAL,
    is_active BOOLEAN DEFAULT TRUE
);
```

### 4.2 Configuration locale
```json
// ~/.syncagent/config.json
{
  "machine_name": "laptop-julien",
  "server_url": "https://sync.mondomaine.com",
  "auth_token": "token-secret-stocké-localement",
  "local_path": "/home/user/Sync",
  "cdc": {
    "avg_size": 4194304,   // 4 MB moyenne
    "min_size": 1048576,   // 1 MB minimum
    "max_size": 8388608    // 8 MB maximum
  },
  "ignore_patterns": [".git", "*.tmp", ".DS_Store", "Thumbs.db"]
}
```

**Ignore patterns** : Syntaxe gitignore-like (glob patterns)
- `*.tmp` → tous les fichiers .tmp
- `.git` → dossier .git
- `build/` → dossier build et son contenu
- `!important.tmp` → exception (ne pas ignorer)

Un fichier `.syncignore` à la racine du dossier sync peut également être utilisé.
- **Note :** `.syncignore` est lui-même synchronisé entre machines (comme `.gitignore`)
- Si une machine modifie `.syncignore`, les autres machines reçoivent la mise à jour

### 4.2bis SQLite local (état client)
```sql
-- ~/.syncagent/db.sqlite

-- Fichiers locaux (cache des métadonnées)
CREATE TABLE local_files (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL UNIQUE,       -- Chemin relatif dans le dossier sync
    server_file_id INTEGER,          -- ID côté serveur (NULL si nouveau local)
    server_version_id TEXT,          -- Version actuelle sur le serveur
    local_mtime REAL,                -- Modification time local
    local_size INTEGER,
    local_hash TEXT,                 -- Hash du fichier local (pour détecter changements)
    chunk_hashes TEXT,               -- JSON: ["hash1", "hash2", ...] (cache local)
    status TEXT DEFAULT 'synced',    -- synced, modified, pending_upload, conflict
    last_synced_at REAL
);

-- Uploads en attente (modifications locales non encore poussées)
CREATE TABLE pending_uploads (
    id INTEGER PRIMARY KEY,
    path TEXT NOT NULL,
    detected_at REAL,
    attempts INTEGER DEFAULT 0,
    last_attempt_at REAL,
    error TEXT                       -- Dernière erreur si échec
);

-- Chunks localement cachés (optionnel, pour éviter re-téléchargement)
CREATE TABLE local_chunks (
    hash TEXT PRIMARY KEY,
    local_path TEXT,                 -- Chemin cache local
    size INTEGER,
    last_accessed_at REAL
);

-- État global de sync
CREATE TABLE sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
-- Clés:
-- last_sync_at: timestamp dernière sync réussie
-- last_server_version: version serveur connue
-- daemon_started_at: timestamp démarrage daemon
```

**Usage :**
```python
def detect_local_changes():
    """Compare l'état local avec la DB pour détecter les modifs"""
    for path in scan_sync_folder():
        file_stat = os.stat(path)
        db_entry = db.get_local_file(path)

        if not db_entry:
            # Nouveau fichier
            mark_pending_upload(path)
        elif file_stat.st_mtime > db_entry.local_mtime:
            # Fichier modifié
            mark_pending_upload(path)

def mark_synced(path, server_file_id, server_version_id):
    """Marque un fichier comme synchronisé"""
    db.execute("""
        UPDATE local_files
        SET status = 'synced',
            server_file_id = ?,
            server_version_id = ?,
            last_synced_at = ?
        WHERE path = ?
    """, (server_file_id, server_version_id, time.time(), path))
```

### 4.3 Partage de la clé E2EE entre machines

#### Première machine (génération)
```bash
$ syncagent init
> Nom de cette machine: laptop-julien
> URL du serveur: https://sync.mondomaine.com
> Dossier à synchroniser: ~/Sync
> Mot de passe maître (pour chiffrer la clé): ********
> Confirmer le mot de passe: ********

✓ Clé E2EE générée
✓ Machine enregistrée sur le serveur
✓ Configuration sauvegardée

Pour ajouter une autre machine, exportez la clé:
  syncagent export-key > ma-cle.key
```

#### Machines suivantes (import)
```bash
$ syncagent init --import-key ma-cle.key
> Nom de cette machine: desktop-bureau
> URL du serveur: https://sync.mondomaine.com
> Dossier à synchroniser: ~/Sync
> Mot de passe maître: ********

✓ Clé E2EE importée
✓ Machine enregistrée sur le serveur
✓ Configuration sauvegardée
```

#### Format du fichier de clé exporté
```json
// ma-cle.key (fichier à transférer de manière sécurisée)
{
  "version": 1,
  "salt": "base64...",
  "encrypted_master_key": "base64...",
  "key_id": "uuid",
  "created_at": "2025-01-01T00:00:00Z",
  "checksum": "sha256..."  // Pour vérifier l'intégrité
}
```

⚠️ **Sécurité:** Le fichier `.key` doit être transféré de manière sécurisée (USB, AirDrop, partage direct). Ne jamais l'envoyer par email ou messagerie non chiffrée.

### 4.4 CLI
```bash
syncagent init                    # Configure + génère clé E2EE
syncagent unlock                  # Déverrouille la clé (mot de passe)
syncagent lock                    # Verrouille la clé (efface de la mémoire)
syncagent watch                   # Démarre le daemon
syncagent sync                    # Force une sync
syncagent status                  # État local
syncagent conflicts               # Liste les conflits
syncagent register-protocol       # Enregistre syncfile://
syncagent export-key              # Exporte la clé (pour autre machine)
syncagent import-key <file>       # Importe une clé
syncagent change-password         # Change le master password
```

### 4.5 Workflow de sync (upload avec CDC)
```python
def sync_file(file_path: str):
    """Sync un fichier avec Content-Defined Chunking"""

    # 1. Découper avec CDC (frontières basées sur le contenu)
    chunks = content_defined_chunking(file_path)

    # 2. Pour chaque chunk
    chunk_hashes = []
    for offset, length, chunk_data in chunks:
        # Hash AVANT chiffrement (pour identifier le chunk)
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()
        chunk_hashes.append(chunk_hash)

        # Upload le chunk chiffré
        encrypted = encrypt_chunk(chunk_data, e2ee_key)
        api.upload_chunk(chunk_hash, encrypted, file_id)

    # 3. Mettre à jour les métadonnées
    api.update_file_metadata(file_path, chunk_hashes, machine_id)
```

### 4.6 Workflow de sync (download)
```python
def download_file(file_id: str, version_id: str, local_path: str):
    # 1. Récupérer les métadonnées
    metadata = api.get_version(file_id, version_id)
    chunk_hashes = metadata['chunk_hashes']

    # 2. Télécharger et déchiffrer chaque bloc
    with open(local_path, 'wb') as f:
        for chunk_hash in chunk_hashes:
            encrypted = api.download_chunk(chunk_hash)
            decrypted = decrypt_chunk(encrypted, e2ee_key)
            f.write(decrypted)
```

---

## 5. Gestion des Conflits

fileA ()
fileB ()

if fileA


### 5.1 Stratégie : Duplication automatique
Quand deux machines modifient le même fichier depuis la même version de base :
```
document.txt                        ← Version principale (ou locale)
document (conflit - laptop).txt     ← Version du laptop
document (conflit - desktop).txt    ← Version du desktop
```

### 5.1bis Cas particulier : Delete vs Modify
Si machine A supprime un fichier et machine B le modifie (en parallèle) :
- **La modification gagne** → le fichier n'est PAS supprimé
- Créer un fichier conflit : `document (conflit - machineB).ext`
- Marquer comme conflit à résoudre par l'utilisateur
- L'utilisateur peut ensuite :
  - Garder le fichier modifié
  - Supprimer définitivement
  - Restaurer la version avant suppression

### 5.2 Détection (côté serveur)
```python
def handle_file_update(file_id, new_version, machine_id, parent_version_id):
    current = db.get_current_version(file_id)

    if parent_version_id == current.id:
        # Mise à jour linéaire → OK
        db.set_current_version(file_id, new_version)
    else:
        # Conflit ! La version parente n'est pas la version actuelle
        db.create_conflict_branch(file_id, new_version, machine_id)
        db.mark_file_conflicted(file_id)
```

### 5.3 Reconstruction (côté client)
```python
def handle_conflicts():
    conflicts = api.get_conflicts()

    for conflict in conflicts:
        file_path = conflict['path']
        branches = conflict['branches']

        for branch in branches:
            machine_name = branch['machine']
            version_id = branch['version_id']

            # Créer le fichier conflit
            conflict_path = f"{file_path} (conflit - {machine_name})"
            download_file(conflict['file_id'], version_id, conflict_path)
```

### 5.4 Résolution
L'utilisateur choisit manuellement :
1. Garde une version → supprime les autres branches
2. Renomme une version comme principale
3. Fusionne manuellement (copier-coller)

Via l'UI web ou le client local.

---

## 6. Block Storage (Abstrait)

### 6.1 Interface abstraite
```python
from abc import ABC, abstractmethod
from typing import Optional

class ChunkStorage(ABC):
    """Interface pour le stockage des blocs chiffrés"""

    @abstractmethod
    def put(self, chunk_hash: str, data: bytes, file_id: int) -> None:
        """Upload un bloc chiffré lié à un fichier"""
        pass

    @abstractmethod
    def get(self, chunk_hash: str) -> bytes:
        """Télécharge un bloc chiffré"""
        pass

    @abstractmethod
    def exists(self, chunk_hash: str) -> bool:
        """Vérifie si un bloc existe"""
        pass

    @abstractmethod
    def delete(self, chunk_hash: str) -> None:
        """Supprime un bloc"""
        pass

    @abstractmethod
    def delete_by_file(self, file_id: int) -> int:
        """Supprime tous les blocs d'un fichier. Retourne le nombre de blocs supprimés."""
        pass
```

### 6.2 Implémentation Local FS (dev/test)
```python
import os
from pathlib import Path

class LocalFSStorage(ChunkStorage):
    """Stockage local pour développement et tests"""

    def __init__(self, base_path: str, db):
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self.db = db  # Référence à la DB pour delete_by_file

    def _chunk_path(self, chunk_hash: str) -> Path:
        # Sous-dossiers par préfixe pour éviter trop de fichiers par dossier
        prefix = chunk_hash[:2]
        return self.base_path / prefix / f"{chunk_hash}.enc"

    def put(self, chunk_hash: str, data: bytes, file_id: int) -> None:
        path = self._chunk_path(chunk_hash)
        path.parent.mkdir(exist_ok=True)
        path.write_bytes(data)
        # Note: l'enregistrement dans la table chunks est fait par l'appelant (API)

    def get(self, chunk_hash: str) -> bytes:
        return self._chunk_path(chunk_hash).read_bytes()

    def exists(self, chunk_hash: str) -> bool:
        return self._chunk_path(chunk_hash).exists()

    def delete(self, chunk_hash: str) -> None:
        path = self._chunk_path(chunk_hash)
        if path.exists():
            path.unlink()

    def delete_by_file(self, file_id: int) -> int:
        """Supprime tous les chunks d'un fichier. Retourne le nombre supprimé."""
        chunks = self.db.execute(
            "SELECT hash FROM chunks WHERE file_id = ?", (file_id,)
        ).fetchall()

        deleted = 0
        for chunk in chunks:
            self.delete(chunk['hash'])
            deleted += 1

        self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        return deleted
```

### 6.3 Implémentation S3-compatible (OVH, AWS, MinIO...)
```python
import boto3
from botocore.exceptions import ClientError

class S3Storage(ChunkStorage):
    """Stockage S3-compatible pour production"""

    def __init__(self, endpoint_url: str, access_key: str, secret_key: str, bucket: str, db):
        self.bucket = bucket
        self.db = db  # Référence à la DB pour delete_by_file
        self.client = boto3.client(
            's3',
            endpoint_url=endpoint_url,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key
        )

    def _key(self, chunk_hash: str) -> str:
        # Préfixe pour distribution dans le bucket
        return f"chunks/{chunk_hash[:2]}/{chunk_hash}.enc"

    def put(self, chunk_hash: str, data: bytes, file_id: int) -> None:
        self.client.put_object(
            Bucket=self.bucket,
            Key=self._key(chunk_hash),
            Body=data
        )
        # Note: l'enregistrement dans la table chunks est fait par l'appelant (API)

    def get(self, chunk_hash: str) -> bytes:
        response = self.client.get_object(
            Bucket=self.bucket,
            Key=self._key(chunk_hash)
        )
        return response['Body'].read()

    def exists(self, chunk_hash: str) -> bool:
        try:
            self.client.head_object(Bucket=self.bucket, Key=self._key(chunk_hash))
            return True
        except ClientError:
            return False

    def delete(self, chunk_hash: str) -> None:
        self.client.delete_object(Bucket=self.bucket, Key=self._key(chunk_hash))

    def delete_by_file(self, file_id: int) -> int:
        """Supprime tous les chunks d'un fichier. Retourne le nombre supprimé."""
        chunks = self.db.execute(
            "SELECT hash FROM chunks WHERE file_id = ?", (file_id,)
        ).fetchall()

        deleted = 0
        for chunk in chunks:
            self.delete(chunk['hash'])
            deleted += 1

        self.db.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
        return deleted
```

### 6.4 Configuration serveur
```json
// config.json serveur
{
  "storage": {
    "type": "local",  // "local" ou "s3"

    // Si type = "local"
    "local_path": "/srv/sync/chunks",

    // Si type = "s3"
    "s3_endpoint": "https://s3.gra.cloud.ovh.net",
    "s3_access_key": "...",
    "s3_secret_key": "...",
    "s3_bucket": "sync-chunks"
  }
}
```

### 6.5 Factory
```python
def create_storage(config: dict) -> ChunkStorage:
    if config['type'] == 'local':
        return LocalFSStorage(config['local_path'])
    elif config['type'] == 's3':
        return S3Storage(
            endpoint_url=config['s3_endpoint'],
            access_key=config['s3_access_key'],
            secret_key=config['s3_secret_key'],
            bucket=config['s3_bucket']
        )
    else:
        raise ValueError(f"Unknown storage type: {config['type']}")
```

### 6.6 Gestion des chunks (v1 - sans déduplication)

**Version 1 (actuelle) :**
- Chaque fichier possède ses propres chunks exclusivement
- Pas de partage de chunks entre fichiers différents
- Suppression simple : quand un fichier est purgé de la corbeille, ses chunks sont supprimés immédiatement
- Avantage : architecture simple, pas de GC complexe, pas de risque de corruption

**Version 2 (prévue ultérieurement) - Déduplication inter-fichiers :**
- Le hash serait calculé sur le contenu EN CLAIR (avant chiffrement)
- Si deux fichiers ont des blocs identiques → même hash → un seul stockage
- Le serveur compterait les références (`ref_count`) pour garbage collection
- GC avec grace period pour éviter les race conditions

### 6.7 Content-Defined Chunking (CDC)

#### Pourquoi CDC plutôt que Fixed-size chunking ?

**Fixed-size (4 MB fixes) :**
```
Fichier original:  [chunk0][chunk1][chunk2][chunk3][chunk4]
Insérer 1 octet:   [XXXXX0][XXXXX1][XXXXX2][XXXXX3][XXXXX4]  ← TOUS décalent
→ 5 chunks à re-uploader
```

**CDC (Content-Defined) :**
```
Fichier original:  [chunk0][chunk1][chunk2][chunk3][chunk4]
Insérer 1 octet:   [chunkA][chunk1][chunk2][chunk3][chunk4]  ← Seul le 1er change
→ 1 chunk à re-uploader
```

#### Algorithme : FastCDC (recommandé)
FastCDC est une implémentation optimisée du Content-Defined Chunking.

```python
# Paramètres CDC
CDC_AVG_SIZE = 4 * 1024 * 1024   # 4 MB moyenne
CDC_MIN_SIZE = 1 * 1024 * 1024   # 1 MB minimum
CDC_MAX_SIZE = 8 * 1024 * 1024   # 8 MB maximum

# Utiliser la lib fastcdc (pip install fastcdc)
from fastcdc import fastcdc
from typing import Iterator

def content_defined_chunking_stream(file_path: str) -> Iterator[tuple[int, int, bytes]]:
    """
    Découpe un fichier en chunks basés sur le contenu (STREAMING).
    Utilise un générateur pour ne jamais charger plus d'un chunk en mémoire.
    Retourne un itérateur de (offset, length, data).
    """
    # fastcdc supporte les fichiers directement (streaming natif)
    with open(file_path, 'rb') as f:
        for chunk in fastcdc(f, CDC_MIN_SIZE, CDC_AVG_SIZE, CDC_MAX_SIZE):
            # Lire uniquement ce chunk (max 8 MB en RAM)
            f.seek(chunk.offset)
            chunk_data = f.read(chunk.length)
            yield (chunk.offset, chunk.length, chunk_data)

# Note : La lib fastcdc accepte un file object ou bytes.
# En passant un file object, elle lit en streaming.
```

#### Alternative : Rolling hash maison (Rabin fingerprint)
```python
import hashlib

# Constantes pour Rabin fingerprint
PRIME = 31
MODULUS = 2**32
MASK = (1 << 20) - 1  # Détermine la taille moyenne (~1 MB avec ce mask)

def rolling_hash_chunking(data: bytes) -> list[bytes]:
    """
    Implémentation simple de CDC avec rolling hash.
    Les frontières sont définies quand le hash "matche" un pattern.
    """
    chunks = []
    start = 0
    window_size = 48  # Fenêtre glissante

    hash_value = 0

    for i in range(len(data)):
        # Ajouter le nouveau byte au hash
        hash_value = (hash_value * PRIME + data[i]) % MODULUS

        # Vérifier si on a trouvé une frontière
        if i - start >= CDC_MIN_SIZE:
            if (hash_value & MASK) == MASK or i - start >= CDC_MAX_SIZE:
                chunks.append(data[start:i])
                start = i
                hash_value = 0

    # Dernier chunk
    if start < len(data):
        chunks.append(data[start:])

    return chunks
```

#### Workflow de sync avec CDC
```python
def sync_file_cdc(file_path: str, file_id: int):
    """Sync un fichier avec Content-Defined Chunking"""

    # 1. Découper avec CDC
    chunks = content_defined_chunking(file_path)

    # 2. Pour chaque chunk
    chunk_hashes = []
    for offset, length, chunk_data in chunks:
        # Hash pour identifier le chunk
        chunk_hash = hashlib.sha256(chunk_data).hexdigest()
        chunk_hashes.append(chunk_hash)

        # Upload le chunk chiffré (lié à ce fichier)
        encrypted = encrypt_chunk(chunk_data, e2ee_key)
        api.upload_chunk(chunk_hash, encrypted, file_id)

    # 3. Mettre à jour les métadonnées
    api.update_file_metadata(file_path, chunk_hashes, machine_id)
```

#### Avantages CDC
| Scénario | Fixed-size | CDC |
|----------|-----------|-----|
| Modification au milieu | 1 chunk | 1 chunk |
| Insertion au début | **N chunks** | 1-2 chunks |
| Suppression d'une partie | **N chunks** | 1-2 chunks |
| Delta sync même fichier | Efficace | **Très efficace** |

---

## 7. Protocol Handler

### 7.1 Format
```
syncfile://open?path=<relative_path>
syncfile://reveal?path=<relative_path>
```

### 7.2 Sécurité
- Vérifie que le path est dans le dossier sync
- N'exécute jamais de commandes arbitraires

### 7.3 Enregistrement par OS

#### Windows (Registry)
```python
import winreg
import sys

def register_protocol_windows():
    """Enregistre syncfile:// dans le registre Windows"""
    exe_path = sys.executable  # ou chemin vers syncagent.exe

    # HKEY_CURRENT_USER\Software\Classes\syncfile
    key_path = r"Software\Classes\syncfile"

    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path) as key:
        winreg.SetValue(key, "", winreg.REG_SZ, "URL:SyncAgent Protocol")
        winreg.SetValueEx(key, "URL Protocol", 0, winreg.REG_SZ, "")

    # Commande à exécuter
    command_path = rf"{key_path}\shell\open\command"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, command_path) as key:
        winreg.SetValue(key, "", winreg.REG_SZ, f'"{exe_path}" protocol "%1"')
```

#### macOS (Info.plist + LaunchServices)
```xml
<!-- Dans l'app bundle: Info.plist -->
<key>CFBundleURLTypes</key>
<array>
    <dict>
        <key>CFBundleURLName</key>
        <string>SyncAgent Protocol</string>
        <key>CFBundleURLSchemes</key>
        <array>
            <string>syncfile</string>
        </array>
    </dict>
</array>
```

```python
# Si pas d'app bundle (script Python), utiliser pyobjc
# pip install pyobjc-framework-CoreServices
from CoreServices import LSSetDefaultHandlerForURLScheme
from Foundation import NSBundle

def register_protocol_macos():
    """Enregistre syncfile:// via LaunchServices"""
    bundle_id = NSBundle.mainBundle().bundleIdentifier()
    LSSetDefaultHandlerForURLScheme("syncfile", bundle_id)
```

#### Linux (.desktop file)
```ini
# ~/.local/share/applications/syncagent-protocol.desktop
[Desktop Entry]
Name=SyncAgent Protocol Handler
Exec=/usr/local/bin/syncagent protocol %u
Type=Application
NoDisplay=true
MimeType=x-scheme-handler/syncfile;
```

```python
import subprocess
from pathlib import Path

def register_protocol_linux():
    """Enregistre syncfile:// via xdg-mime"""
    desktop_file = Path.home() / ".local/share/applications/syncagent-protocol.desktop"
    desktop_file.parent.mkdir(parents=True, exist_ok=True)

    desktop_file.write_text("""[Desktop Entry]
Name=SyncAgent Protocol Handler
Exec=/usr/local/bin/syncagent protocol %u
Type=Application
NoDisplay=true
MimeType=x-scheme-handler/syncfile;
""")

    # Enregistrer comme handler par défaut
    subprocess.run([
        "xdg-mime", "default",
        "syncagent-protocol.desktop",
        "x-scheme-handler/syncfile"
    ])
```

#### Handler unifié (CLI)
```python
# syncagent protocol "syncfile://open?path=/docs/file.txt"
import sys
from urllib.parse import urlparse, parse_qs

def handle_protocol_url(url: str):
    """Parse et exécute une URL syncfile://"""
    parsed = urlparse(url)

    if parsed.scheme != "syncfile":
        raise ValueError(f"Schéma invalide: {parsed.scheme}")

    action = parsed.netloc  # "open" ou "reveal"
    params = parse_qs(parsed.query)

    path = params.get("path", [None])[0]
    if not path:
        raise ValueError("Paramètre 'path' requis")

    # Vérifier que le path est dans le dossier sync
    full_path = get_sync_folder() / path.lstrip("/")
    if not full_path.resolve().is_relative_to(get_sync_folder()):
        raise ValueError("Path hors du dossier sync")

    if action == "open":
        open_file(full_path)
    elif action == "reveal":
        reveal_in_explorer(full_path)
```

---

## 8. WebSocket Client (Sync temps réel)

### 8.1 Architecture
```
┌─────────────┐     WebSocket      ┌─────────────┐     WebSocket      ┌─────────────┐
│   Laptop    │◄──────────────────►│   Serveur   │◄──────────────────►│   Desktop   │
│   (daemon)  │                    │  (FastAPI)  │                    │   (daemon)  │
└─────────────┘                    └─────────────┘                    └─────────────┘

1. Laptop modifie un fichier
2. Laptop upload les chunks + métadonnées
3. Serveur broadcast "file_updated" aux autres clients WebSocket
4. Desktop reçoit la notif → télécharge immédiatement
```

### 8.2 Connexion
```python
# Client daemon
import websockets
import asyncio

WS_URL = "wss://sync.mondomaine.com/ws"

async def connect_websocket(token: str):
    async with websockets.connect(
        WS_URL,
        extra_headers={"Authorization": f"Bearer {token}"}
    ) as ws:
        await handle_messages(ws)
```

### 8.3 Format des messages (JSON)
```python
# Serveur → Client : Notification de changement
{
    "type": "file_updated",
    "file_id": 123,
    "path": "/docs/rapport.pdf",
    "version_id": "uuid...",
    "machine": "laptop-julien",
    "timestamp": 1704067200.0
}

# Serveur → Client : Nouveau conflit
{
    "type": "conflict_detected",
    "file_id": 123,
    "path": "/docs/rapport.pdf",
    "branches": [
        {"machine": "laptop", "version_id": "..."},
        {"machine": "desktop", "version_id": "..."}
    ]
}

# Serveur → Client : Fichier supprimé
{
    "type": "file_deleted",
    "file_id": 123,
    "path": "/docs/ancien.pdf",
    "deleted_by": "laptop-julien"
}

# Client → Serveur : Heartbeat
{
    "type": "ping"
}

# Serveur → Client : Heartbeat response
{
    "type": "pong"
}
```

### 8.4 Événements
| Type | Direction | Description |
|------|-----------|-------------|
| `file_updated` | Serveur → Client | Un fichier a été modifié par une autre machine |
| `file_deleted` | Serveur → Client | Un fichier a été supprimé |
| `conflict_detected` | Serveur → Client | Nouveau conflit détecté |
| `machine_online` | Serveur → Client | Une machine s'est connectée |
| `machine_offline` | Serveur → Client | Une machine s'est déconnectée |
| `ping` | Client → Serveur | Heartbeat (toutes les 30s) |
| `pong` | Serveur → Client | Réponse heartbeat |

### 8.5 Reconnexion automatique
```python
async def websocket_loop(token: str):
    """Boucle de reconnexion avec backoff exponentiel"""
    backoff = 1  # Délai initial en secondes
    max_backoff = 60  # Délai max

    while True:
        try:
            async with websockets.connect(WS_URL, ...) as ws:
                backoff = 1  # Reset après connexion réussie
                await handle_messages(ws)
        except (ConnectionClosed, ConnectionRefused) as e:
            logger.warning(f"WebSocket déconnecté: {e}")
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, max_backoff)  # Backoff exponentiel
```

### 8.6 Côté serveur (FastAPI)
```python
from fastapi import WebSocket, WebSocketDisconnect
from typing import Dict

# Connexions actives par machine_id
active_connections: Dict[str, WebSocket] = {}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    # Authentifier via token
    token = websocket.headers.get("Authorization", "").replace("Bearer ", "")
    machine = authenticate_machine(token)
    if not machine:
        await websocket.close(code=4001)
        return

    await websocket.accept()
    active_connections[machine.machine_id] = websocket

    try:
        while True:
            data = await websocket.receive_json()
            if data.get("type") == "ping":
                await websocket.send_json({"type": "pong"})
    except WebSocketDisconnect:
        del active_connections[machine.machine_id]

async def broadcast_to_others(source_machine_id: str, message: dict):
    """Envoie un message à tous les clients sauf la source"""
    for machine_id, ws in active_connections.items():
        if machine_id != source_machine_id:
            await ws.send_json(message)
```

### 8.7 Flux complet (temps réel)
```
1. Laptop: File watcher détecte modification
2. Laptop: Debounce 250ms + délai 3s
3. Laptop: Upload chunks chiffrés
4. Laptop: POST /api/files (métadonnées)
5. Serveur: Enregistre la nouvelle version
6. Serveur: broadcast_to_others("file_updated", {...})
7. Desktop: Reçoit notification WebSocket
8. Desktop: GET /api/files/{id} + télécharge chunks
9. Desktop: Déchiffre et écrit le fichier
10. Sync complète en < 5s (selon taille fichier)
```

### 8.8 Reconnexion après offline (catch-up)

Quand un client revient après une déconnexion (quelques heures, jours...) :

#### État local persisté
```json
// ~/.syncagent/state.json
{
  "last_sync_at": 1704067200.0,
  "last_server_version": 42,
  "pending_uploads": ["/docs/local-edit.txt"]
}
```

#### Flux de reconnexion
```
1. Client reconnecte WebSocket
2. Client: GET /api/changes?since=<last_sync_at>
3. Serveur retourne tous les changements depuis cette date
4. Client télécharge les fichiers modifiés/créés
5. Client supprime localement les fichiers supprimés
6. Client push ses modifications locales (pending_uploads)
7. Détection de conflits si nécessaire
8. Mise à jour de last_sync_at
```

#### API endpoint
```python
@app.get("/api/changes")
def get_changes(since: float, machine_id: str):
    """Retourne tous les changements depuis un timestamp"""
    changes = []

    # Fichiers modifiés/créés (par d'autres machines)
    updated = db.execute("""
        SELECT f.id, f.path, v.id as version_id, v.machine_id, f.updated_at
        FROM files f
        JOIN versions v ON f.current_version_id = v.id
        WHERE f.updated_at > ?
        AND v.machine_id != ?
        AND f.is_deleted = FALSE
    """, (since, machine_id)).fetchall()

    for row in updated:
        changes.append({
            "type": "updated",
            "file_id": row['id'],
            "path": row['path'],
            "version_id": row['version_id'],
            "updated_at": row['updated_at']
        })

    # Fichiers supprimés
    deleted = db.execute("""
        SELECT id, path, deleted_at
        FROM files
        WHERE is_deleted = TRUE
        AND deleted_at > ?
    """, (since,)).fetchall()

    for row in deleted:
        changes.append({
            "type": "deleted",
            "file_id": row['id'],
            "path": row['path'],
            "deleted_at": row['deleted_at']
        })

    return {
        "changes": sorted(changes, key=lambda x: x.get('updated_at') or x.get('deleted_at')),
        "server_time": time.time()
    }
```

#### Gestion des modifications locales pendant offline
```python
async def reconnect_sync():
    """Sync complète après reconnexion"""
    state = load_local_state()

    # 1. Récupérer les changements serveur
    changes = await api.get_changes(since=state['last_sync_at'])

    # 2. Appliquer les changements distants
    for change in changes['changes']:
        if change['type'] == 'updated':
            await download_and_apply(change)
        elif change['type'] == 'deleted':
            delete_local_file(change['path'])

    # 3. Push les modifications locales (peut créer des conflits)
    for path in state.get('pending_uploads', []):
        await sync_file(path)

    # 4. Mettre à jour l'état
    state['last_sync_at'] = changes['server_time']
    state['pending_uploads'] = []
    save_local_state(state)
```

#### Cas de conflit post-reconnexion
Si le client a modifié un fichier localement ET ce fichier a été modifié sur le serveur :
- Le serveur détecte le conflit (parent_version_id != current_version_id)
- Création des fichiers conflits comme d'habitude
- L'utilisateur résout manuellement

---

## 9. Sécurité Récapitulatif

| Scénario d'attaque | Résultat |
|--------------------|----------|
| Hack du serveur API | Accès métadonnées seulement, pas de contenu |
| Hack de la base de données | Métadonnées structurelles, pas de contenu |
| Hack du block storage OVH | Blocs chiffrés, inutilisables |
| Interception HTTPS (MITM) | Blocs chiffrés, inutilisables |
| Vol du token d'API | Upload/delete possible, mais pas de lecture |
| Vol de la clé E2EE seule | Impossible d'accéder au serveur |
| Accès physique à une machine | Compromission (mais limité à cette machine) |

---

## 10. Tâches d'implémentation

### Phase 1: Crypto & Core
- [ ] Fonction de dérivation de clé (Argon2id)
- [ ] Chiffrement/déchiffrement AES-GCM
- [ ] Stockage sécurisé de la clé locale
- [ ] CLI: `init`, `unlock`, `export-key`, `import-key`

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : dérivation de clé avec vecteurs de test connus
- [ ] Tests unitaires : chiffrement/déchiffrement (round-trip, edge cases)
- [ ] Tests unitaires : stockage clé (keyring mock, fallback file)
- [ ] Tests CLI : `init`, `unlock`, `export-key`, `import-key` (subprocess ou click testing)
- [ ] Mypy strict sur tous les modules crypto
- [ ] Ruff zero warnings
- [ ] Coverage ≥ 95%

### Phase 2: Content-Defined Chunking (CDC)
- [ ] Implémentation CDC avec rolling hash (FastCDC ou Rabin)
- [ ] Taille moyenne ~4 MB, min 1 MB, max 8 MB
- [ ] Hash SHA-256 des blocs
- [ ] Upload/download blocs chiffrés
- [ ] Liaison chunks → fichier (pas de déduplication inter-fichiers en v1)

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : chunking avec fichiers de différentes tailles (0, 1B, 1MB, 10MB, 100MB)
- [ ] Tests unitaires : stabilité des frontières (insertion au milieu ne change pas les autres chunks)
- [ ] Tests unitaires : hash SHA-256 cohérent entre runs
- [ ] Tests intégration : upload/download round-trip
- [ ] Benchmark : performance chunking sur gros fichiers
- [ ] Mypy strict + Ruff zero warnings
- [ ] Coverage ≥ 95%

### Phase 3: Serveur Métadonnées
- [ ] FastAPI app + SQLite WAL
- [ ] API REST (auth, files, chunks, conflicts)
- [ ] Détection de conflits (version parente)
- [ ] Authentification par token

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : chaque endpoint API (auth, files, chunks, conflicts, trash)
- [ ] Tests unitaires : détection de conflits (cas linéaire, cas divergent)
- [ ] Tests unitaires : validation tokens (valide, expiré, invalide)
- [ ] Tests unitaires : invitations (création, usage unique, expiration)
- [ ] Tests intégration : workflow complet (register → upload → download)
- [ ] Tests : background jobs (purge trash, cleanup sessions)
- [ ] Mypy strict + Ruff zero warnings
- [ ] Coverage ≥ 95% (hors templates Web UI)

### Phase 4: Block Storage
- [ ] Intégration OVH S3/Swift (boto3)
- [ ] Upload/download blocs
- [ ] Suppression chunks à la purge de corbeille (simple, pas de GC complexe)

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : LocalFSStorage (put, get, exists, delete, delete_by_file)
- [ ] Tests unitaires : S3Storage avec moto (mock S3)
- [ ] Tests : factory create_storage()
- [ ] Tests intégration : round-trip complet (upload → download → verify)
- [ ] Mypy strict + Ruff zero warnings
- [ ] Coverage ≥ 95%

### Phase 5: Sync Engine
- [ ] File watcher (watchdog)
- [ ] Algorithme de sync (push/pull)
- [ ] Gestion des conflits (duplication)
- [ ] SQLite local pour état

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : file watcher (création, modification, suppression, renommage)
- [ ] Tests unitaires : debounce et délai 3s
- [ ] Tests unitaires : détection changements locaux vs DB
- [ ] Tests unitaires : création fichiers conflit (nommage correct)
- [ ] Tests unitaires : gestion fichiers verrouillés (Windows mock)
- [ ] Tests intégration : sync bidirectionnelle complète
- [ ] Mypy strict + Ruff zero warnings
- [ ] Coverage ≥ 95%

### Phase 6: Web UI
- [ ] File browser (métadonnées seulement)
- [ ] Liste des conflits
- [ ] Résolution de conflits
- [ ] Status des machines
- [ ] Liens `syncfile://`

**Tests & Qualité (TDD) :**
- [ ] Tests : setup wizard (redirection, création admin, validation password)
- [ ] Tests : CSRF protection
- [ ] Tests : session cookies (HttpOnly, Secure, expiration)
- [ ] Tests fonctionnels : navigation, recherche (httpx TestClient)
- [ ] Note : templates HTML exclus de l'objectif coverage
- [ ] Mypy strict + Ruff zero warnings

### Phase 7: Protocol Handler
- [ ] Parsing URL
- [ ] Enregistrement Windows/macOS/Linux
- [ ] Intégration Web UI

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : parsing URLs syncfile:// (valides et invalides)
- [ ] Tests unitaires : validation machine_id et path
- [ ] Tests unitaires : sécurité (path traversal, injection)
- [ ] Tests : enregistrement protocol (mocks registry/plist/xdg)
- [ ] Mypy strict + Ruff zero warnings
- [ ] Coverage ≥ 95%

### Phase 8: Tray Icon
- [ ] pystray setup
- [ ] Icônes par état
- [ ] Menu contextuel

**Tests & Qualité (TDD) :**
- [ ] Tests unitaires : état icon (idle, syncing, error, conflict)
- [ ] Tests unitaires : menu actions (callbacks)
- [ ] Note : tray icon exclu de l'objectif coverage (GUI)
- [ ] Mypy strict + Ruff zero warnings

---

**Note Méthodologie TDD :**
Chaque phase inclut maintenant ses propres tests et critères de qualité. L'approche recommandée est :
1. Écrire les tests d'abord (red)
2. Implémenter le code minimal pour passer les tests (green)
3. Refactorer si nécessaire (refactor)
4. Vérifier mypy strict + ruff avant chaque commit
5. Maintenir coverage ≥ 95% tout au long du développement

---

## 11. Stack Technique

| Composant | Technologie |
|-----------|-------------|
| Client | Python 3.11+ |
| Crypto | cryptography (AES-GCM), argon2-cffi |
| File watcher | watchdog |
| HTTP client | httpx ou requests |
| DB locale | SQLite |
| Tray icon | pystray + Pillow |
| Serveur | FastAPI + Jinja2 + HTMX |
| CSS | Pico CSS |
| DB serveur | SQLite WAL |
| Block storage | OVH S3 (boto3) |
| Auth | JWT ou tokens simples |

---

## 12. Avantages de cette Architecture

| Aspect | Bénéfice |
|--------|----------|
| **Zero Knowledge** | Le serveur ne peut JAMAIS lire les fichiers |
| **Hack-proof** | Même un hack total du serveur = 0 fuite de données |
| **HTTPS simple** | Plus besoin de SSH, déploiement facile |
| **Scalable** | Block storage = stockage illimité, pas cher |
| **CDC optimisé** | Modifications partielles = peu de données transférées |
| **Architecture simple (v1)** | Pas de GC complexe, suppression directe à la purge |
| **Multi-device** | Même clé E2EE = accès sur toutes les machines |
| **Conflits simples** | Duplication automatique, résolution manuelle |
| **Évolutif** | Déduplication inter-fichiers prévue en v2 |

---

## Appendix A: Détails techniques complémentaires

### A.1 Limites

| Limite | Valeur | Note |
|--------|--------|------|
| Taille max fichier | 1 TB | Limite pratique S3 multipart |
| Nom de fichier | 255 caractères | Standard FS |
| Profondeur chemin | 4096 caractères | Standard FS |
| Machines par compte | Illimité | - |
| Session admin | 24h (configurable) | - |
| Invitation token | 24h (expire) | Usage unique |
| Corbeille rétention | 30j (configurable) | - |

### A.2 Fichiers et dossiers spéciaux

#### Dossiers vides
- Les dossiers vides sont synchronisés via `files.is_directory = TRUE`
- Pas de chunks associés (`current_version_id = NULL`)
- Suppression : si le dossier devient non-vide (fichiers ajoutés), passage à `is_directory = FALSE`

#### Liens symboliques (symlinks)
- **Ignorés complètement** (comportement par défaut)
- Rationale : évite les boucles infinies et les problèmes de sécurité
- Le file watcher ignore les symlinks
- Pas de sync des liens, pas d'erreur

#### Détection des renommages
- Implémenté via les chunk_hashes
- Si un fichier disparaît et un nouveau fichier apparaît avec les mêmes chunk_hashes :
  - Détection de renommage → mise à jour du path, pas de re-upload
  - Optimisation côté client avant upload

```python
def detect_rename(disappeared_files: list, new_files: list) -> list[tuple]:
    """Détecte les renommages via correspondance de chunks"""
    renames = []

    for old_file in disappeared_files:
        old_hashes = set(old_file.chunk_hashes)
        for new_file in new_files:
            new_hashes = set(new_file.chunk_hashes)
            # Si tous les chunks correspondent → renommage
            if old_hashes == new_hashes:
                renames.append((old_file.path, new_file.path))
                break

    return renames
```

### A.3 Gestion des fichiers verrouillés (Windows)

Sur Windows, certains fichiers peuvent être verrouillés par d'autres applications (Excel, Word, etc.).

**Stratégie : Skip & Retry avec backoff**

```python
import time
from typing import Optional

MAX_LOCK_RETRIES = 5
LOCK_RETRY_DELAYS = [1, 2, 5, 10, 30]  # Secondes, backoff progressif

def try_read_file(file_path: str) -> Optional[bytes]:
    """Tente de lire un fichier, avec retry si verrouillé"""
    for attempt in range(MAX_LOCK_RETRIES):
        try:
            with open(file_path, 'rb') as f:
                return f.read()
        except PermissionError:
            # Fichier verrouillé
            if attempt < MAX_LOCK_RETRIES - 1:
                delay = LOCK_RETRY_DELAYS[min(attempt, len(LOCK_RETRY_DELAYS) - 1)]
                logger.warning(f"File locked: {file_path}, retrying in {delay}s")
                time.sleep(delay)
            else:
                logger.error(f"File still locked after {MAX_LOCK_RETRIES} attempts: {file_path}")
                return None
    return None

def sync_with_lock_handling(file_path: str):
    """Sync avec gestion des fichiers verrouillés"""
    data = try_read_file(file_path)

    if data is None:
        # Fichier verrouillé → ajouter à pending_uploads pour retry ultérieur
        mark_pending_upload(file_path, error="File locked by another process")
        # Notification tray icon
        notify_user(f"Fichier verrouillé, sync différée : {file_path}")
        return False

    # Continuer avec la sync normale
    return sync_file_data(file_path, data)
```

**Comportement :**
1. Premier essai immédiat
2. Si verrouillé : retry après 1s, 2s, 5s, 10s, 30s
3. Si toujours verrouillé après 5 tentatives :
   - Fichier marqué comme "pending_upload" avec erreur
   - Notification utilisateur (tray icon)
   - Retry automatique au prochain scan (5 min)

### A.4 Configuration WebSocket (heartbeat/timeout)

```json
// config.json (client)
{
  "websocket": {
    "heartbeat_interval": 30,    // Secondes entre chaque ping (défaut: 30)
    "reconnect_min_delay": 1,    // Délai min reconnexion (défaut: 1s)
    "reconnect_max_delay": 60    // Délai max reconnexion (défaut: 60s)
  }
}

// config.json (serveur)
{
  "websocket": {
    "timeout": 90,               // Ferme si pas de ping depuis X secondes (défaut: 3x heartbeat)
    "max_connections": 100       // Limite de connexions simultanées (défaut: 100)
  }
}
```

**Valeurs recommandées :**
- `heartbeat_interval`: 30s (équilibre entre réactivité et overhead)
- `timeout`: 90s (3x heartbeat, tolère 2 pings manqués)
- `reconnect_min_delay`: 1s (réactivité après déconnexion brève)
- `reconnect_max_delay`: 60s (évite spam sur serveur down)

### A.5 Daemon Single Instance (PID file + Lock)

Le daemon ne doit s'exécuter qu'une seule fois par machine. Si un deuxième processus tente de démarrer, il doit détecter l'instance existante et refuser de se lancer proprement.

**Approche : PID file avec file locking (state of the art cross-platform)**

```python
import sys
import os
import fcntl  # Unix only - voir alternative Windows ci-dessous
from pathlib import Path

class SingleInstanceLock:
    """Garantit qu'une seule instance du daemon tourne"""

    def __init__(self, lock_file: Path):
        self.lock_file = lock_file
        self.lock_fd = None

    def acquire(self) -> bool:
        """
        Tente d'acquérir le lock.
        Retourne True si succès, False si une autre instance tourne.
        """
        self.lock_file.parent.mkdir(parents=True, exist_ok=True)

        try:
            self.lock_fd = open(self.lock_file, 'w')
            if sys.platform == 'win32':
                import msvcrt
                msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

            # Écrire le PID pour debug
            self.lock_fd.write(str(os.getpid()))
            self.lock_fd.flush()
            return True

        except (IOError, OSError):
            # Lock déjà acquis par une autre instance
            if self.lock_fd:
                self.lock_fd.close()
                self.lock_fd = None
            return False

    def release(self):
        """Libère le lock"""
        if self.lock_fd:
            try:
                if sys.platform == 'win32':
                    import msvcrt
                    msvcrt.locking(self.lock_fd.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self.lock_fd, fcntl.LOCK_UN)
            finally:
                self.lock_fd.close()
                self.lock_fd = None
                # Supprimer le fichier de lock
                try:
                    self.lock_file.unlink()
                except OSError:
                    pass

    def __enter__(self):
        if not self.acquire():
            raise RuntimeError("Another instance is already running")
        return self

    def __exit__(self, *args):
        self.release()


# Usage dans le daemon
def start_daemon():
    """Démarre le daemon avec protection single instance"""
    lock_file = Path.home() / ".syncagent" / "daemon.lock"
    lock = SingleInstanceLock(lock_file)

    if not lock.acquire():
        print("Error: SyncAgent daemon is already running.", file=sys.stderr)
        print("Use 'syncagent status' to check the current daemon.", file=sys.stderr)
        sys.exit(1)

    try:
        # Démarrer le daemon normalement
        run_daemon()
    finally:
        lock.release()
```

**Comportement :**
- Au démarrage : tente d'acquérir un file lock exclusif sur `~/.syncagent/daemon.lock`
- Si le lock échoue : message d'erreur clair et exit code 1
- Si le lock réussit : écriture du PID et démarrage du daemon
- À l'arrêt : libération du lock et suppression du fichier

**Avantages de cette approche :**
- Cross-platform (Windows, macOS, Linux)
- Résistant aux crashes (le lock est libéré automatiquement par l'OS)
- Pas de stale PID file (le lock garantit que le processus tourne vraiment)
- Simple et robuste

### A.6 Permissions des fichiers

**Les permissions (mode Unix / ACL Windows) ne sont PAS synchronisées.**

Rationale :
- Les permissions varient entre OS (chmod vs ACL)
- Les UID/GID ne correspondent pas entre machines
- Le serveur est Zero-Knowledge (ne devrait pas stocker des métadonnées sensibles)
- Cas d'usage principal : documents utilisateur (permissions standard suffisent)

**Comportement :**
- À l'upload : les permissions locales sont ignorées
- Au download : le fichier est créé avec les permissions par défaut (umask sur Unix)
- Les fichiers gardent les permissions de l'utilisateur qui exécute le daemon

**Note :** Si une synchronisation de permissions est nécessaire, c'est envisageable en v2 via des métadonnées optionnelles.