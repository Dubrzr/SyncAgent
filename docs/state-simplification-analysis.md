# Analyse : Simplification du State Local

## Proposition Initiale

> "Ne peut-on pas simplifier en gardant juste fpath/mtime/size/chunks/hashes dans notre state,
> et pas un état de transfert ? Quand on lance le sync alors on regarde les diffs locaux avec
> les fpath/mtime; on demande au serveur quels fichiers sont incomplets, on fait le diff et
> on upload que le nécessaire (on considère globalement que la vérité c'est le serveur)"

## Architecture Actuelle

### Tables SQLite (state.py)

```
local_files:
├── id (PK)
├── path (UNIQUE)
├── server_file_id      ← ID côté serveur
├── server_version      ← Version côté serveur (pour conflits)
├── local_mtime         ← Timestamp local
├── local_size          ← Taille locale
├── local_hash          ← Hash du contenu (rarement utilisé)
├── chunk_hashes        ← JSON array des hashes de chunks
├── status              ← Enum: NEW, MODIFIED, SYNCED, CONFLICT, DELETED
└── last_synced_at      ← Timestamp du dernier sync

pending_uploads:
├── id (PK)
├── path
├── detected_at
├── attempts
├── last_attempt_at
└── error

upload_progress:
├── id (PK)
├── path
├── total_chunks
├── uploaded_chunks
├── chunk_hashes
├── uploaded_hashes     ← Pour resume chunk par chunk
├── started_at
└── updated_at

sync_state:
├── key (PK)
└── value               ← last_sync_at, last_server_version, last_change_cursor
```

### Utilisation du Status

| Status | Signification | Déclencheur |
|--------|--------------|-------------|
| `NEW` | Fichier local non encore synchronisé | scan_local_changes() |
| `MODIFIED` | Modifié depuis dernier sync | mtime/size changé |
| `SYNCED` | En phase avec le serveur | mark_synced() |
| `CONFLICT` | Conflit détecté | mark_conflict() |
| `DELETED` | Supprimé localement | fichier disparu |
| `PENDING_UPLOAD` | (Inutilisé en pratique) | - |

### Flux de Données Actuel

```
                     scan_local_changes()
                            │
                            ▼
              ┌─────────────────────────────┐
              │     Compare avec state DB   │
              │  - mtime/size → MODIFIED?   │
              │  - pas dans DB → NEW?       │
              │  - pas sur disk → DELETED?  │
              └─────────────────────────────┘
                            │
                            ▼
                   emit_events(queue)
                            │
                            ▼
                    Workers execute
                            │
                            ▼
                    mark_synced()
                    status = SYNCED
```

## Analyse Critique

### Le status est DÉRIVÉ, pas INTRINSÈQUE

**Constat clé** : On peut calculer le status à partir des données brutes :

```python
def get_derived_status(path: str, state: State, base_path: Path) -> str:
    tracked = state.get_file(path)
    local_path = base_path / path

    if tracked is None:
        if local_path.exists():
            return "NEW"           # Existe local, pas en DB
        return None                # N'existe nulle part

    if not local_path.exists():
        return "DELETED"           # En DB mais pas sur disque

    stat = local_path.stat()
    if stat.st_mtime > tracked.local_mtime or stat.st_size != tracked.local_size:
        return "MODIFIED"          # Différent de ce qu'on a enregistré

    return "SYNCED"                # Identique à ce qu'on a enregistré
```

**Conclusion** : Le champ `status` est redondant. On peut le supprimer.

### Ce Qu'On Garde vs. Ce Qu'On Supprime

| Champ | Garder | Raison |
|-------|--------|--------|
| `path` | ✅ | Identifiant |
| `local_mtime` | ✅ | Détecter modifications locales |
| `local_size` | ✅ | Détecter modifications locales |
| `server_version` | ✅ | Détecter conflits |
| `chunk_hashes` | ⚠️ | Optionnel, optimise le resume |
| `status` | ❌ | Calculable |
| `server_file_id` | ❌ | Non utilisé (path = clé) |
| `local_hash` | ❌ | Redondant avec chunk_hashes |
| `last_synced_at` | ⚠️ | Debug uniquement |

| Table | Garder | Raison |
|-------|--------|--------|
| `local_files` | ✅ | Simplifiée |
| `pending_uploads` | ❌ | Non nécessaire |
| `upload_progress` | ❌ | Server sait via chunk_exists |
| `sync_state` | ✅ | Curseur incrémental |

## Schéma Simplifié Proposé

```sql
-- Table principale simplifiée
CREATE TABLE synced_files (
    path TEXT PRIMARY KEY,
    local_mtime REAL NOT NULL,      -- Timestamp lors du dernier sync
    local_size INTEGER NOT NULL,     -- Taille lors du dernier sync
    server_version INTEGER NOT NULL, -- Version serveur (pour conflits)
    chunk_hashes TEXT,               -- JSON array (optionnel, optimisation)
    synced_at REAL NOT NULL          -- Quand synchronisé
);

-- Métadonnées sync (unchanged)
CREATE TABLE sync_state (
    key TEXT PRIMARY KEY,
    value TEXT
);
```

## Nouveau Flux de Sync

```
┌──────────────────────────────────────────────────────────────────┐
│                        SYNC START                                 │
└────────────────────────────┬─────────────────────────────────────┘
                             │
     ┌───────────────────────┴───────────────────────┐
     ▼                                               ▼
┌─────────────────────┐                   ┌──────────────────────┐
│  SCAN LOCAL FILES   │                   │  FETCH REMOTE STATE  │
│                     │                   │                      │
│  Pour chaque fichier│                   │  - list_files()      │
│  sur disque:        │                   │  - ou /api/changes   │
│                     │                   │                      │
│  Si non tracké →    │                   └──────────┬───────────┘
│    LOCAL_CREATED    │                              │
│                     │                              │
│  Si mtime/size ≠ → │                              │
│    LOCAL_MODIFIED   │                              │
│                     │                              │
│  Pour chaque tracké │                              │
│  non sur disque:    │                              │
│    LOCAL_DELETED    │                              │
└─────────────────────┘                              │
             │                                       │
             └───────────────────┬───────────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    DIFF & EMIT EVENTS   │
                    │                         │
                    │  Conflit si:            │
                    │  - Local modifié ET     │
                    │  - Server version ≠     │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │   WORKERS EXECUTE       │
                    │                         │
                    │  Upload:                │
                    │  - Chunk file           │
                    │  - chunk_exists() skip  │
                    │  - Upload missing only  │
                    │  - Commit (create/update)│
                    │                         │
                    │  Download:              │
                    │  - Get server file      │
                    │  - Download chunks      │
                    │  - Assemble             │
                    └────────────┬────────────┘
                                 │
                                 ▼
                    ┌─────────────────────────┐
                    │    UPDATE LOCAL STATE   │
                    │                         │
                    │  INSERT OR REPLACE INTO │
                    │  synced_files (         │
                    │    path,                │
                    │    local_mtime,         │
                    │    local_size,          │
                    │    server_version,      │
                    │    chunk_hashes,        │
                    │    synced_at            │
                    │  )                      │
                    └─────────────────────────┘
```

## Gestion des Cas Particuliers

### Resume d'Upload Interrompu

**Actuellement** : Table `upload_progress` avec chunks uploadés

**Proposé** :
1. Re-hash le fichier pour obtenir les chunk_hashes
2. Pour chaque chunk : `chunk_exists()` sur le serveur
3. Upload uniquement les chunks manquants

**Impact** : Légèrement plus lent (re-hash) mais plus simple et robuste.

### Détection de Conflit

```python
def check_conflict(path: str, state: State, server_file) -> bool:
    tracked = state.get_file(path)
    if tracked is None:
        return False  # Nouveau fichier, pas de conflit

    # Le serveur a une version plus récente ET le local a changé
    return (server_file.version > tracked.server_version and
            local_was_modified(path, tracked))
```

### Fichier Modifié Pendant Download

**Actuellement** : `check_download_conflict()` compare mtime/size

**Proposé** : Identique - on compare toujours mtime/size avec ce qu'on a stocké.

```python
def check_download_conflict(path, tracked_mtime, tracked_size) -> bool:
    stat = Path(path).stat()
    return stat.st_mtime > tracked_mtime or stat.st_size != tracked_size
```

## API Serveur Nécessaire

### Existant et Suffisant

| Endpoint | Usage |
|----------|-------|
| `GET /api/files` | Liste des fichiers serveur |
| `GET /api/files/{path}` | Métadonnées d'un fichier |
| `GET /api/chunks/{hash}/exists` | Chunk existe ? (pour dedup) |
| `POST /api/chunks` | Upload chunk |
| `GET /api/changes?since=` | Changements incrémentaux |

### Optionnel (Optimisation)

```
GET /api/files/incomplete
→ Liste des fichiers avec chunks manquants (uploads interrompus)
```

Pas strictement nécessaire car on peut :
1. Re-hash le fichier local
2. Utiliser `chunk_exists()` pour chaque chunk

## Plan d'Implémentation

### Phase 1 : Simplifier le State

1. **Créer nouvelle table `synced_files`** avec schéma simplifié
2. **Migrer les données existantes** depuis `local_files`
3. **Supprimer les tables obsolètes** : `pending_uploads`, `upload_progress`

### Phase 2 : Adapter le Scanner

1. **Modifier `scan_local_changes()`** pour ne plus utiliser `status`
2. **Calculer le status à la volée** basé sur mtime/size comparison

### Phase 3 : Adapter les Workers

1. **Upload** :
   - Re-hash pour obtenir chunks
   - `chunk_exists()` pour chaque
   - Upload manquants seulement

2. **Download** :
   - Vérifier conflit via mtime/size
   - Download et update state

### Phase 4 : Supprimer le Code Obsolète

1. Supprimer `FileStatus` enum
2. Supprimer `PendingUpload`, `UploadProgress` classes
3. Supprimer méthodes : `add_pending_upload()`, `mark_chunk_uploaded()`, etc.

## Fichiers à Modifier

| Fichier | Changements |
|---------|-------------|
| `src/syncagent/client/state.py` | Refonte complète |
| `src/syncagent/client/sync/change_scanner.py` | Adapter scan logic |
| `src/syncagent/client/sync/transfers/upload.py` | Supprimer tracking local |
| `src/syncagent/client/sync/transfers/download.py` | Simplifier |
| `src/syncagent/client/sync/workers/*.py` | Adapter workers |
| `src/syncagent/client/sync/conflict.py` | Simplifier |
| `tests/client/test_state.py` | Refonte tests |
| `tests/client/test_sync.py` | Adapter tests |

## Estimation de l'Effort

| Phase | Complexité | Fichiers |
|-------|------------|----------|
| Phase 1 | Moyenne | 1 fichier + migration |
| Phase 2 | Faible | 1 fichier |
| Phase 3 | Moyenne | 3-4 fichiers |
| Phase 4 | Faible | Nettoyage |
| Tests | Moyenne | 3-4 fichiers |

## Risques et Mitigations

| Risque | Mitigation |
|--------|------------|
| Migration de données | Script de migration + backup |
| Perte de progress upload | Re-hash + chunk_exists (plus lent mais safe) |
| Conflits non détectés | Tests exhaustifs des edge cases |
| Performance re-hash | Cache chunk_hashes (optionnel) |

## Recommandation

**Approche recommandée** : Simplification progressive

1. ✅ Garder `chunk_hashes` dans la table (évite re-hash constant)
2. ✅ Supprimer `status` (calculable)
3. ✅ Supprimer `pending_uploads` (non nécessaire)
4. ⚠️ Supprimer `upload_progress` (utiliser chunk_exists)
5. ✅ Supprimer `server_file_id` et `local_hash`

Le résultat final serait une table `synced_files` avec 5-6 colonnes au lieu de 3 tables et 15+ colonnes.

## Optimisations Décidées

### 1. Cache chunk_hashes local

**Décision** : Garder `chunk_hashes` dans la table locale.

**Raison** :
- Évite de re-hasher le fichier entier à chaque resume/sync
- Le hashing est CPU-intensif sur gros fichiers
- Stockage négligeable (quelques Ko par fichier)

### 2. API `/api/files/incomplete` côté serveur

**Nouvel endpoint** :
```
GET /api/files/incomplete
→ Liste des fichiers avec chunks manquants (uploads interrompus pour cette machine)
```

**Structure réponse** :
```json
{
  "incomplete_files": [
    {
      "path": "docs/rapport.pdf",
      "expected_chunks": ["abc123", "def456", "ghi789"],
      "uploaded_chunks": ["abc123"],
      "missing_chunks": ["def456", "ghi789"]
    }
  ]
}
```

**Utilisation** :
- Au démarrage du sync, appeler cet endpoint
- Pour chaque fichier incomplet dont le local existe toujours :
  - Re-vérifier que les chunk_hashes locaux correspondent
  - Upload les chunks manquants
  - Commit le fichier

## Architecture: Gestion des Chunks

### Où se fait l'upload des chunks ?

```
┌─────────────────────────────────────────────────────────────────────┐
│                         UPLOAD FLOW                                  │
└─────────────────────────────────────────────────────────────────────┘

    UploadWorker                    FileUploader                    Server
         │                               │                            │
         │  execute(event)               │                            │
         │──────────────────────────────▶│                            │
         │                               │                            │
         │                               │  1. Read local file        │
         │                               │  2. chunk_file() → chunks  │
         │                               │  3. Pour chaque chunk:     │
         │                               │     chunk_exists(hash)?────▶│
         │                               │◀─────────── true/false ────│
         │                               │     Si false:              │
         │                               │       encrypt_chunk()      │
         │                               │       upload_chunk()───────▶│
         │                               │                            │
         │                               │  4. create_file() ou       │
         │                               │     update_file() (commit)─▶│
         │                               │                            │
         │  UploadResult                 │                            │
         │◀──────────────────────────────│                            │
```

### Comment les workers savent quels chunks uploader ?

1. **FileUploader.upload_file()** :
   - Lit le fichier local
   - Appelle `chunk_file(local_path)` → liste de chunks avec hashes
   - Pour chaque chunk, vérifie `chunk_exists(hash)` sur serveur
   - Upload uniquement les chunks manquants
   - Commit avec `create_file()` ou `update_file()`

2. **State simplifié** : On ne stocke plus `upload_progress` localement
   - Le serveur track quels chunks existent via son storage
   - `chunk_exists()` sert de "résumé" distribué

### Où se fait le download des chunks ?

```
┌─────────────────────────────────────────────────────────────────────┐
│                        DOWNLOAD FLOW                                 │
└─────────────────────────────────────────────────────────────────────┘

   DownloadWorker                  FileDownloader                   Server
         │                               │                            │
         │  execute(event)               │                            │
         │──────────────────────────────▶│                            │
         │                               │                            │
         │                               │  1. get_file_metadata()────▶│
         │                               │◀──────── ServerFile ───────│
         │                               │                            │
         │                               │  2. get_file_chunks()──────▶│
         │                               │◀──────── [hash1, hash2] ───│
         │                               │                            │
         │                               │  3. Pour chaque chunk:     │
         │                               │     download_chunk(hash)───▶│
         │                               │◀────── encrypted data ─────│
         │                               │     decrypt_chunk()        │
         │                               │                            │
         │                               │  4. Assemble chunks        │
         │                               │     Write to temp file     │
         │                               │     Atomic rename          │
         │                               │                            │
         │  DownloadResult               │                            │
         │◀──────────────────────────────│                            │
```

## FileWatcher et Scan : Éviter les Race Conditions

### Problème Identifié

```
Timeline dangereuse:
────────────────────────────────────────────────────────────────────────
t0: Watcher démarre
t1: User modifie file.txt (mtime=100)
t2: Watcher détecte la modif, émet event avec mtime=100 dans metadata
t3: Scan démarre, lit file.txt (mtime=100)
t4: User re-modifie file.txt (mtime=150)
t5: Scan termine, émet event avec mtime=100 (valeur lue à t3, obsolète!)
t6: Si on remplace aveuglément, on perd l'info de la modif à t4
────────────────────────────────────────────────────────────────────────
```

**Problème clé** : Le timestamp de l'event (quand il a été créé) ≠ le mtime du fichier.
Ce qui compte c'est le **mtime observé**, pas la date de création de l'event.

### Solution : mtime-aware deduplication

**Modifier `EventQueue.put()`** pour comparer les mtime des fichiers :

```python
def put(self, event: SyncEvent) -> bool:
    with self._lock:
        old_event = self._events.get(event.path)
        if old_event:
            # Comparer les mtime des fichiers, pas les timestamps des events
            old_mtime = old_event.metadata.get("mtime", 0)
            new_mtime = event.metadata.get("mtime", 0)

            if new_mtime < old_mtime:
                # L'ancien event a un mtime plus récent - garder l'ancien
                logger.debug(
                    "Ignoring event with older mtime for %s: new_mtime=%s < old_mtime=%s",
                    event.path, new_mtime, old_mtime
                )
                return True  # Event "accepté" mais non stocké

            if new_mtime == old_mtime:
                # Même mtime - garder l'event le plus récent (dernière observation)
                if event.timestamp <= old_event.timestamp:
                    return True

        self._events[event.path] = event
        # ... rest of method
```

**Prérequis** : Les events doivent inclure `mtime` dans leur metadata :

```python
# Dans scan_local_changes() et FileWatcher
event = SyncEvent.create(
    event_type=SyncEventType.LOCAL_MODIFIED,
    path=relative_path,
    source=SyncEventSource.LOCAL,
    metadata={"mtime": stat.st_mtime, "size": stat.st_size},
)
```

### Flow Recommandé

```
┌─────────────────────────────────────────────────────────────────────┐
│                    SYNC STARTUP SEQUENCE                             │
└─────────────────────────────────────────────────────────────────────┘

1. Créer EventQueue
2. Démarrer FileWatcher (observe les changements en temps réel)
3. Lancer scan_local_changes() + fetch_remote_changes()
4. Les events du scan arrivent dans la queue
5. Les events du watcher arrivent EN PARALLÈLE
6. La queue garde l'event avec le timestamp le plus récent
7. Démarrer les workers pour traiter la queue

Avantage:
- Aucune modification n'est manquée
- Les modifications pendant le scan sont capturées par le watcher
- L'event le plus récent (watcher) gagne
```

## Implémentations Réalisées ✅

### mtime-aware deduplication (Implémenté)

Les fichiers suivants ont été modifiés :

1. **`types.py`** : Ajout de `LocalFileInfo` dataclass
```python
@dataclass
class LocalFileInfo:
    path: str
    mtime: float
    size: int
```

2. **`change_scanner.py`** :
   - `LocalChanges.created/modified` utilisent maintenant `LocalFileInfo`
   - `scan_local_changes()` peuple mtime/size
   - `emit_events()` passe mtime/size dans metadata des events

3. **`watcher.py`** : `_inject_event()` ajoute mtime/size à metadata

4. **`queue.py`** : `put()` utilise mtime-aware deduplication

5. **`cli/sync.py`** : Watcher démarre AVANT le scan initial
```python
# Start watcher BEFORE scan to capture modifications during scan
watcher = FileWatcher(sync_folder, queue)
watcher.start()

# Initial scan - events from scanner and watcher arrive in parallel
# Queue deduplicates by mtime: watcher wins if file modified during scan
fetch_and_emit_changes()
```

6. **Tests** : 5 nouveaux tests dans `test_queue.py` :
   - `test_mtime_deduplication_newer_wins`
   - `test_mtime_deduplication_older_ignored`
   - `test_mtime_deduplication_same_mtime_uses_timestamp`
   - `test_mtime_deduplication_no_mtime_fallback`
   - `test_mtime_deduplication_mixed_local_remote`

---

## Critique de la Spec et Corrections

### Issue 1: Remote Events Non Gérés

**Problème** : La déduplication mtime ne s'applique qu'aux LOCAL events.

**Comportement actuel** :
- LOCAL vs LOCAL : Compare mtime ✅
- REMOTE vs REMOTE : Compare timestamp (fallback)
- LOCAL vs REMOTE : Le dernier arrivé gagne

**Clarification** : C'est correct car :
- Les events REMOTE n'ont pas de mtime local
- Un LOCAL et REMOTE pour le même path = conflit réel, géré par workers

### Issue 2: Event Types et Priorité

**Problème** : Quid de `DELETE` vs `MODIFIED` avec même mtime ?

**Décision** : On garde l'event le plus récent (par mtime puis timestamp).
Le type d'event n'affecte pas la déduplication car :
- Si un fichier est supprimé puis recréé, le mtime change
- Si même mtime, c'est le même fichier → seul le dernier compte

### Issue 3: Race Condition Download

**Problème** : Fichier modifié PENDANT le download.

**Solution existante** : `check_download_conflict()` est appelé AVANT le download.

**Amélioration proposée** : Double-check APRÈS download, AVANT rename.

```python
# Dans FileDownloader.download_file()
def download_file(...):
    # ... download to temp file ...

    # Double-check before atomic rename
    if local_path.exists():
        current_stat = local_path.stat()
        if current_stat.st_mtime != expected_mtime:
            raise DownloadConflictError("File modified during download")

    # Safe to rename
    temp_file.rename(local_path)
```

**Status** : À implémenter (Phase suivante)

### Issue 4: Change Cursor Timing

**Problème** : Cursor mis à jour après fetch, pas après process.

**Impact** : Perte de changes si crash entre fetch et process.

**Solution** : Mettre à jour le cursor APRÈS que les workers aient traité les events.

**Status** : À vérifier/corriger (Phase suivante)

### Issue 5: DELETE Tracking

**Question** : Sans status, comment tracker LOCAL_DELETED ?

**Réponse** :
- Fichier dans state DB mais pas sur disque → DELETED
- Après sync réussi → Supprimer de state DB
- Si crash avant sync → Au restart, scan détectera toujours DELETED

**Edge case** : Crash entre suppression locale et sync serveur.
- Au restart : fichier absent du disque ET de la state DB (si pas encore tracké)
- Solution : Scan compare aussi avec la liste serveur

### Issue 6: `/api/files/incomplete` Complexité

**Problème** : Les chunks sont content-addressed et partagés.

**Clarification** : Cette API nécessite que le serveur track :
```
pending_uploads:
  - machine_id
  - file_path
  - expected_chunk_hashes[]
  - created_at
```

**Décision** : Reporter cette optimisation. Utiliser `chunk_exists()` pour le MVP.

---

## Best Practices Appliquées

### 1. Single Responsibility Principle (SRP)

- `EventQueue` : Stockage et déduplication uniquement
- `Workers` : Exécution et résolution de conflits
- `Scanner` : Détection de changements
- Pas de logique métier dans la queue

### 2. Immutability et Data Classes

- `LocalFileInfo` : Dataclass immutable pour transporter mtime/size
- `SyncEvent` : Dataclass avec métadonnées explicites

### 3. Fail-Fast avec Logging

```python
if new_mtime < old_mtime:
    logger.debug("Ignoring event with older mtime...")
    return True  # Accepté mais non stocké
```

### 4. Defensive Programming

```python
# Dans watcher - le fichier peut disparaître entre détection et stat
if change.change_type != ChangeType.DELETED and change.path.exists():
    try:
        stat = change.path.stat()
        metadata["mtime"] = stat.st_mtime
    except OSError:
        pass  # File deleted between check and stat
```

### 5. Testabilité

- Tests unitaires isolés pour chaque comportement
- Pas de dépendances temporelles (sauf sleep explicite pour timestamps)

---

## Questions Ouvertes

1. **Migration des données existantes ?**
   - Créer script de migration
   - Tester sur copie de la DB avant déploiement

2. **Timeout pour fichiers incomplets ?**
   - Combien de temps garder les chunks orphelins ?
   - Proposition : 7 jours, puis nettoyage automatique

3. **Double-check mtime après download ?**
   - Ajouter vérification avant atomic rename
   - À implémenter en Phase suivante

4. **Change cursor timing ?**
   - Vérifier le flux actuel
   - Corriger si nécessaire
