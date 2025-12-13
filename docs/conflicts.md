# Gestion des Conflits - Spécifications

## 1. Définition d'un Conflit

Un conflit survient quand **le même fichier** est modifié sur **plusieurs machines** depuis la **même version de base**, avant synchronisation.

```
Timeline:
  Machine A: file.txt v1 → modifie → file.txt v1' (local)
  Machine B: file.txt v1 → modifie → file.txt v1'' (local)

  Machine A upload v1' → serveur accepte → file.txt v2 (serveur)
  Machine B upload v1'' → CONFLIT (parent=v1, mais serveur a v2)
```

**Important:** Un conflit n'existe que si le **contenu est différent**. Si deux machines font la même modification (hash identique), ce n'est PAS un conflit.

## 2. Stratégie de Résolution

**Pattern : "Server Wins + Local Preserved"** (inspiré Dropbox/Syncthing)

| Principe | Description |
|----------|-------------|
| **Aucune perte de données** | Les deux versions sont conservées |
| **Hash comparison first** | Si hash identique → pas de conflit, juste sync |
| **Serveur gagne** | La version serveur devient le fichier principal |
| **Local renommé** | La version locale devient `.conflict-*` |
| **Notification** | L'utilisateur est alerté du conflit |
| **Résolution manuelle** | L'utilisateur décide quelle version garder |

## 3. Architecture de Gestion des Conflits

```
┌─────────────────────────────────────────────────────────────────┐
│                     CONFLICT HANDLING                           │
├─────────────────────────────────────────────────────────────────┤
│  Scanner (emit_events)                                          │
│    └── Détecte conflits au scan (local+remote changes)          │
│        → Log warning, les deux events passent                   │
│                                                                 │
│  Queue (EventQueue)                                             │
│    └── Simple déduplication par path (dernier event gagne)      │
│        → PAS de logique métier (SRP)                            │
│                                                                 │
│  Workers (exécution) ← Gestion des conflits ICI                 │
│    ├── DownloadWorker → check_download_conflict()               │
│    │   └── Vérifie mtime AVANT download                         │
│    │   └── Si modifié localement → .conflict-* + download       │
│    │                                                            │
│    └── UploadWorker → resolve_upload_conflict()                 │
│        └── Attrape VERSION_CONFLICT du serveur                  │
│        └── Compare hashes, renomme local → .conflict-*          │
└─────────────────────────────────────────────────────────────────┘
```

**Pourquoi les conflits sont gérés au niveau des workers (pas la queue) :**
1. Couvre la race condition scan → exécution
2. Vérification au moment exact où l'opération se produit
3. Queue reste simple (Single Responsibility Principle)
4. Source de vérité = état actuel du fichier/serveur, pas l'event

## 4. Détection des Conflits

### 4.1 À l'upload (VERSION_CONFLICT)

```python
# Dans UploadWorker._handle_conflict()
try:
    client.update_file(path, parent_version=local_version)
except ConflictError as e:
    # parent_version != server_version → appeler resolve_upload_conflict()
    resolution = resolve_upload_conflict(
        client, encryption_key, local_path, relative_path, state, base_path
    )
    # resolution.outcome peut être:
    #   - ALREADY_SYNCED: hash identique, pas de vrai conflit
    #   - RESOLVED: local renommé, serveur téléchargé
    #   - RETRY_NEEDED: race condition, réessayer
```

### 4.2 Détection précoce (EarlyConflictError)

```python
# Avant de commencer l'upload, dans UploadWorker._do_work()
if event.event_type == SyncEventType.LOCAL_MODIFIED:
    server_file = client.get_file(path)
    expected_version = event.metadata.get("parent_version")

    if expected_version and server_file.version != expected_version:
        # Conflit détecté avant même de commencer l'upload
        raise EarlyConflictError(
            path=path,
            local_version=expected_version,
            server_version=server_file.version,
            server_hash=server_file.content_hash,
        )
```

### 4.3 Au download (check_download_conflict)

```python
# Dans DownloadWorker._do_work(), AVANT de télécharger
resolution = check_download_conflict(
    local_path=local_path,
    relative_path=relative_path,
    state=self._sync_state,
    base_path=self._base_path,
)

if resolution.outcome == ConflictOutcome.RETRY_NEEDED:
    raise CancelledException("Download conflict resolution failed")

if resolution.outcome == ConflictOutcome.RESOLVED:
    logger.info(f"Download conflict resolved: local saved as {resolution.conflict_path}")
# Puis continuer avec le download
```

**Scénarios détectés par check_download_conflict() :**

| Situation | Action |
|-----------|--------|
| Fichier n'existe pas localement | Pas de conflit, proceed |
| Fichier existe mais pas tracké | Conflit! Renommer local → .conflict-* |
| Fichier tracké, mtime/size identique | Pas de conflit, proceed |
| Fichier tracké, mtime ou size changé | Conflit! Renommer local → .conflict-* |

### 4.4 Au scan initial

Quand le même chemin apparaît dans `local_changes` ET `remote_changes` :

| Local | Remote | Action |
|-------|--------|--------|
| CREATED | CREATED | Conflit détecté au worker |
| MODIFIED | MODIFIED | Conflit détecté au worker |
| DELETED | MODIFIED | Modification gagne (remote event) |
| MODIFIED | DELETED | Modification gagne (local event) |
| DELETED | DELETED | OK (même intention) |

## 5. Flux de Résolution

### 5.1 Conflit détecté à l'upload

```
1. UploadWorker attrape ConflictError ou EarlyConflictError
2. Appelle resolve_upload_conflict():
   a. Récupérer info serveur (hash, version)
   b. Comparer hash local vs hash serveur
      → Si identique: marquer SYNCED, FIN (pas de vrai conflit)
   c. Vrai conflit - safe_rename_for_conflict() → .conflict-*
   d. Télécharger version serveur → fichier.txt
   e. Mettre à jour state DB:
      - fichier.txt: status=SYNCED, version=serveur
      - fichier.conflict-*: status=NEW (sera uploadé au prochain sync)
   f. Notifier l'utilisateur
3. Retourner UploadResult avec conflict_path
```

### 5.2 Conflit détecté au download

```
1. DownloadWorker appelle check_download_conflict() AVANT download
2. Si fichier local modifié depuis le scan:
   a. Calculer hash local
   b. safe_rename_for_conflict() → .conflict-*
   c. Ajouter .conflict-* au state DB comme NEW
   d. Notifier l'utilisateur
3. Continuer avec le download normal
```

### 5.3 Protection contre les Race Conditions

```python
def safe_rename_for_conflict(local_path: Path) -> Path:
    """Renomme le fichier local en .conflict-* de manière sûre."""
    # 1. Capturer mtime avant
    mtime_before = local_path.stat().st_mtime

    # 2. Générer nom de conflit (avec millisecondes)
    conflict_path = generate_conflict_filename(local_path)

    # 3. Renommer
    local_path.rename(conflict_path)

    # 4. Vérifier mtime après (sur le fichier renommé)
    mtime_after = conflict_path.stat().st_mtime

    if mtime_after != mtime_before:
        # Le fichier a été modifié pendant le renommage!
        # Annuler: remettre le fichier à sa place
        conflict_path.rename(local_path)
        raise RaceConditionError("File modified during conflict resolution")

    return conflict_path
```

## 6. Format du Fichier Conflit

```
{stem}.conflict-{YYYYMMDD}-{HHMMSSmmm}-{machine}{extension}

Format timestamp: YYYYMMDD-HHMMSSmmm (avec millisecondes pour unicité)

Exemples:
  rapport.txt       → rapport.conflict-20250113-143052123-laptop.txt
  image.png         → image.conflict-20250113-143052456-desktop.png
  Makefile          → Makefile.conflict-20250113-143052789-server
  archive.tar.gz    → archive.tar.conflict-20250113-143052012-pc.gz
```

- **machine** : Nom de la machine locale (sanitized, pas de caractères spéciaux)
- **timestamp** : Moment de la détection du conflit avec **millisecondes** (évite collisions)

## 7. Cas Particuliers

### 7.1 Conflits Multi-Machines (N machines)

```
Scénario: 3 machines modifient le même fichier en parallèle

État initial: file.txt v1 (toutes machines sync)
  Machine A: modifie → v1'
  Machine B: modifie → v1''
  Machine C: modifie → v1'''

Timeline:
  1. A upload v1' → serveur v2 (A gagne, premier arrivé)
  2. B upload v1'' → ConflictError
     → resolve_upload_conflict() → .conflict-*-machineB.txt
  3. C upload v1''' → ConflictError
     → resolve_upload_conflict() → .conflict-*-machineC.txt
  4. B upload file.conflict-...-machineB.txt → serveur accepte
  5. C upload file.conflict-...-machineC.txt → serveur accepte
  6. Sync normal: tous téléchargent les fichiers manquants

État final (identique sur toutes machines):
  ├── file.txt                                       (version A)
  ├── file.conflict-20250113-143052123-machineB.txt  (version B)
  └── file.conflict-20250113-143055456-machineC.txt  (version C)
```

### 7.2 Même modification sur plusieurs machines (faux conflit)

```
Scénario: A et B font la MÊME modification

Machine A: file.txt v1 → ajoute "TODO" → hash=abc123
Machine B: file.txt v1 → ajoute "TODO" → hash=abc123 (identique!)

Timeline:
  1. A upload → serveur v2 (hash=abc123)
  2. B upload → ConflictError (parent mismatch)
     → resolve_upload_conflict() compare hash
     → IDENTIQUE! ConflictOutcome.ALREADY_SYNCED
     → B marque SYNCED (v2), pas de .conflict-* créé
```

### 7.3 Delete vs Modify

```
Machine A: supprime fichier.txt
Machine B: modifie fichier.txt

Résolution: La MODIFICATION GAGNE
- fichier.txt reste (version de B)
- Notification: "fichier.txt was deleted on Machine A but modified locally"
- Pas de .conflict-* dans ce cas
```

### 7.4 Modification locale entre scan et download

```
1. Scanner détecte: REMOTE_MODIFIED pour file.txt
2. Event queued pour download
3. USER MODIFIE file.txt LOCALEMENT
4. DownloadWorker commence:
   a. check_download_conflict() détecte mtime changé
   b. Renomme local → file.conflict-*-machinename.txt
   c. Download serveur → file.txt
5. Au prochain scan: .conflict-* détecté comme NEW → upload
```

### 7.5 Fichier créé des deux côtés (même nom)

```
Machine A: crée nouveau.txt (hash=aaa), upload → serveur v1
Machine B: crée nouveau.txt (hash=bbb), tente upload

Résolution:
1. B reçoit ConflictError (fichier existe déjà)
2. resolve_upload_conflict() compare hash: aaa != bbb
3. B renomme son fichier → nouveau.conflict-*
4. B download version serveur → nouveau.txt
```

## 8. Notifications

### 8.1 Notification OS

```python
notify_conflict(
    filename="rapport.txt",
    other_machine="laptop-julien"
)
# → "Conflit détecté: rapport.txt - Vérifiez le fichier .conflict-*"
```

### 8.2 Tray Icon

- État `CONFLICT` avec icône spécifique
- Menu affiche le nombre de conflits non résolus

## 9. State DB

### 9.1 Status possibles

```python
class FileStatus(Enum):
    NEW = "new"           # Fichier local non encore uploadé
    MODIFIED = "modified" # Modifié localement depuis dernier sync
    SYNCED = "synced"     # Synchronisé avec serveur
    DELETED = "deleted"   # Supprimé localement
    CONFLICT = "conflict" # Conflit détecté, en attente résolution
```

## 10. Implémentation (FAIT)

### 10.1 Fichiers implémentés

| Fichier | Implémentation |
|---------|----------------|
| `sync/conflict.py` | `resolve_upload_conflict()`, `check_download_conflict()`, `safe_rename_for_conflict()`, `generate_conflict_filename()` avec ms |
| `sync/workers/upload.py` | `_handle_conflict()` attrape ConflictError et EarlyConflictError |
| `sync/workers/download.py` | Appelle `check_download_conflict()` avant download |
| `sync/change_scanner.py` | `emit_events()` détecte delete vs modify |
| `sync/queue.py` | Simple déduplication (pas de logique conflit) |
| `client/notifications.py` | `notify_conflict()` |

### 10.2 ConflictOutcome

```python
class ConflictOutcome(Enum):
    ALREADY_SYNCED = "already_synced"  # Hashes matched, no real conflict
    RESOLVED = "resolved"              # Local renamed, server downloaded
    RETRY_NEEDED = "retry_needed"      # Race condition, need to retry
```

### 10.3 ConflictResolution

```python
@dataclass
class ConflictResolution:
    outcome: ConflictOutcome
    conflict_path: Path | None = None
    server_version: int | None = None
```

## 11. Tests

### 11.1 Scénarios testés

1. Upload → ConflictError + hash différent → fichier renommé + download
2. Upload → ConflictError + hash identique → marquer SYNCED
3. EarlyConflictError (pre-transfer) + hash différent → même flux
4. EarlyConflictError + hash identique → skip upload, marquer SYNCED
5. Download avec fichier local modifié → renommer local, puis download
6. Download sans fichier local → pas de conflit
7. Delete local + Modify remote → modification gagne
8. Modify local + Delete remote → modification gagne
9. Race condition: fichier modifié pendant résolution → retry
10. Collision timestamp: 2 conflits même seconde → noms différents (ms)

### 11.2 Tests d'intégration

- 2 clients modifient le même fichier (contenu différent) → conflit détecté
- 2 clients modifient le même fichier (même contenu) → pas de conflit
- Client offline modifie, revient online → conflit si serveur a changé
- N machines modifient en parallèle → N-1 fichiers .conflict-*

## 12. Limitations et Améliorations Futures (v2)

### Non implémenté en v1

| Feature | Raison |
|---------|--------|
| **Merge automatique texte** | Complexe, risque de corruption |
| **Stratégies configurables** | "Prefer local", "Prefer remote", etc. - complexifie l'UX |
| **CRDT pour édition temps réel** | Hors scope (on n'est pas Google Docs) |
| **UI de résolution de conflits** | V1 = résolution manuelle via explorateur de fichiers |

### Possibles en v2

- Merge automatique pour fichiers texte simples (git-like 3-way merge)
- Option "always prefer local" ou "always prefer remote" par dossier
- Interface web pour comparer et résoudre les conflits
- Détection de conflits par ligne (pas fichier entier) pour texte
