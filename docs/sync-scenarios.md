# Sync Scenarios - Cas de Synchronisation

Ce document décrit tous les scénarios de synchronisation possibles et comment ils doivent être traités.

## Table des matières

1. [Modèle de données](#modèle-de-données)
2. [Scénarios de base](#scénarios-de-base)
3. [Scénarios multi-machines](#scénarios-multi-machines)
4. [Conflits](#conflits)
5. [Erreurs réseau](#erreurs-réseau)
6. [Cas limites](#cas-limites)
7. [Matrice de décision](#matrice-de-décision)

---

## Modèle de données

### États d'un fichier local

```
┌─────────────┐
│    NEW      │ ──── Fichier créé localement, pas encore sur serveur
└─────────────┘
       │
       ▼ (upload success)
┌─────────────┐
│   SYNCED    │ ──── En sync avec le serveur (version locale == serveur)
└─────────────┘
       │
       ▼ (local modification)
┌─────────────┐
│  MODIFIED   │ ──── Modifié localement, pas encore uploadé
└─────────────┘
       │
       ▼ (conflict detected)
┌─────────────┐
│  CONFLICT   │ ──── Conflit détecté, action utilisateur requise
└─────────────┘

┌─────────────┐
│   DELETED   │ ──── Supprimé localement, suppression à propager au serveur
└─────────────┘
```

### Informations trackées

| Champ | Description |
|-------|-------------|
| `path` | Chemin relatif du fichier |
| `local_mtime` | Timestamp de dernière modification locale |
| `local_size` | Taille du fichier local |
| `local_hash` | Hash SHA-256 du contenu local |
| `server_version` | Numéro de version sur le serveur |
| `server_file_id` | ID du fichier sur le serveur |
| `chunk_hashes` | Liste des hashes des chunks |
| `status` | État actuel (NEW, SYNCED, MODIFIED, etc.) |

---

## Scénarios de base

### SC-01: Nouveau fichier local

**Situation**: Un fichier est créé dans le dossier sync, n'existe pas sur le serveur.

```
Machine A                    Serveur
─────────                    ───────
file.txt (NEW)               (n'existe pas)
```

**Traitement**:
1. Détecter le nouveau fichier (scan ou watcher)
2. Marquer comme `NEW` dans la DB locale
3. Chunker le fichier (CDC)
4. Uploader les chunks manquants
5. `POST /api/files` avec métadonnées + liste chunks
6. Mettre à jour DB locale: `status=SYNCED`, `server_version=1`

**Résultat**: Fichier créé sur serveur avec version 1.

---

### SC-02: Fichier modifié localement

**Situation**: Un fichier synchronisé est modifié localement.

```
Machine A                    Serveur
─────────                    ───────
file.txt (v1, modifié)       file.txt (v1)
local_hash: abc123           content_hash: xyz789
```

**Traitement**:
1. Détecter modification (mtime ou size changé)
2. Marquer comme `MODIFIED`
3. Chunker le nouveau contenu
4. Uploader les nouveaux chunks
5. `PUT /api/files/{path}` avec `parent_version=1`
6. Si succès: `status=SYNCED`, `server_version=2`
7. Si conflit (409): voir [SC-10](#sc-10-conflit-réel)

---

### SC-03: Fichier supprimé localement

**Situation**: Un fichier synchronisé est supprimé du disque local.

```
Machine A                    Serveur
─────────                    ───────
file.txt (DELETED)           file.txt (v1)
(n'existe plus sur disque)
```

**Traitement**:
1. Détecter suppression (fichier dans DB mais pas sur disque)
2. Marquer comme `DELETED`
3. `DELETE /api/files/{path}`
4. Supprimer de la DB locale
5. Serveur met le fichier en corbeille (soft delete)

---

### SC-04: Nouveau fichier sur serveur (pull)

**Situation**: Un fichier existe sur le serveur mais pas en local.

```
Machine A                    Serveur
─────────                    ───────
(n'existe pas)               file.txt (v1)
```

**Traitement**:
1. `GET /api/files` liste tous les fichiers serveur
2. Pour chaque fichier non présent localement:
   - `GET /api/files/{path}/chunks` pour la liste des chunks
   - Télécharger et déchiffrer chaque chunk
   - Assembler le fichier
   - Ajouter à DB locale: `status=SYNCED`, `server_version=1`

---

### SC-05: Fichier modifié sur serveur (pull)

**Situation**: Un fichier a une nouvelle version sur le serveur.

```
Machine A                    Serveur
─────────                    ───────
file.txt (v1, SYNCED)        file.txt (v2)
```

**Traitement**:
1. `GET /api/files` → version serveur = 2, locale = 1
2. Si `status == SYNCED` (pas de modif locale):
   - Télécharger la nouvelle version
   - Écraser le fichier local
   - Mettre à jour: `server_version=2`
3. Si `status == MODIFIED`: voir [SC-10](#sc-10-conflit-réel)

---

### SC-06: Fichier supprimé sur serveur

**Situation**: Un fichier a été supprimé (mis en corbeille) sur le serveur.

```
Machine A                    Serveur
─────────                    ───────
file.txt (v1, SYNCED)        file.txt (deleted_at != null)
```

**Traitement**:
1. `GET /api/files` ne retourne plus le fichier (ou avec `deleted_at`)
2. Si `status == SYNCED`:
   - Supprimer le fichier local
   - Supprimer de la DB locale
3. Si `status == MODIFIED`:
   - Le fichier a été modifié localement après suppression serveur
   - Traiter comme nouveau fichier (re-créer sur serveur)

---

## Scénarios multi-machines

### SC-07: Même fichier créé sur 2 machines

**Situation**: Deux machines créent un fichier avec le même chemin.

```
Machine A                    Serveur                    Machine B
─────────                    ───────                    ─────────
file.txt (NEW)               (vide)                     file.txt (NEW)
hash: aaa                                               hash: bbb
```

**Timeline**:
```
t=0:  A et B créent file.txt
t=1:  A sync → POST /api/files → version 1 (hash=aaa)
t=2:  B sync → POST /api/files → ERREUR 409 (fichier existe)
```

**Traitement pour B**:
1. B reçoit 409 Conflict
2. B compare son hash avec celui du serveur
3. Si hash identique → faux conflit, marquer SYNCED
4. Si hash différent → créer copie `.conflict-*`, télécharger version serveur

---

### SC-08: Modifications concurrentes (même fichier)

**Situation**: Deux machines modifient le même fichier "en même temps".

```
Machine A                    Serveur                    Machine B
─────────                    ───────                    ─────────
file.txt (v1, MODIFIED)      file.txt (v1)              file.txt (v1, MODIFIED)
new_hash: aaa                                           new_hash: bbb
```

**Timeline**:
```
t=0:  A et B ont file.txt v1
t=1:  A modifie file.txt
t=2:  B modifie file.txt
t=3:  A sync → PUT avec parent_version=1 → v2 créée
t=4:  B sync → PUT avec parent_version=1 → 409 Conflict (v2 existe)
```

**Traitement pour B**:
1. B reçoit 409 Conflict avec `current_version=2`
2. B télécharge la version serveur (v2)
3. B compare hash local avec hash serveur v2
4. Si identique → faux conflit
5. Si différent → conflit réel, créer `.conflict-*`

---

### SC-09: Faux conflit (même contenu)

**Situation**: Deux machines font la même modification.

```
Machine A                    Serveur                    Machine B
─────────                    ───────                    ─────────
file.txt (MODIFIED)          file.txt (v1)              file.txt (MODIFIED)
new_hash: xyz                                           new_hash: xyz (identique!)
```

**Traitement**:
1. A sync → v2 créée avec hash=xyz
2. B sync → 409 Conflict
3. B récupère hash serveur = xyz = hash local
4. **Faux conflit détecté**: juste mettre à jour `server_version=2`
5. Pas de fichier `.conflict-*` créé

---

### SC-10: Conflit réel

**Situation**: Deux machines ont des contenus différents.

```
Machine A                    Serveur                    Machine B
─────────                    ───────                    ─────────
file.txt (v2, SYNCED)        file.txt (v2)              file.txt (v1→MODIFIED)
hash: aaa                    hash: aaa                  hash: bbb
```

**Traitement pour B** (qui sync après A):
1. B tente `PUT /api/files/file.txt` avec `parent_version=1`
2. Serveur répond 409: version actuelle = 2
3. B détecte conflit réel (hash différent)
4. B renomme son fichier local → `file.conflict-20241212-153000-MachineB.txt`
5. B télécharge la version serveur (v2) → `file.txt`
6. B notifie l'utilisateur du conflit
7. État: `file.txt` = v2 (SYNCED), `.conflict-*` = version B (non trackée)

---

## Conflits

### Types de conflits

| Type | Description | Résolution |
|------|-------------|------------|
| **Faux conflit** | Même hash des deux côtés | Auto-résolu (pas d'action) |
| **Conflit réel** | Hash différents | Créer copie `.conflict-*` |
| **Conflit delete/modify** | Un supprime, l'autre modifie | Recréer le fichier |
| **Conflit rename** | Renommage concurrent | Traiter comme delete+create |

### Format des fichiers de conflit

```
{nom}.conflict-{YYYYMMDD}-{HHMMSS}-{machine}.{ext}

Exemple:
rapport.conflict-20241212-153045-LAPTOP-JULIEN.docx
```

### SC-11: Conflit delete/modify

**Situation**: A supprime un fichier, B le modifie.

```
Timeline:
t=0:  A et B ont file.txt v1
t=1:  A supprime file.txt
t=2:  B modifie file.txt
t=3:  A sync → DELETE → fichier en corbeille serveur
t=4:  B sync → PUT parent_version=1 → 404 Not Found
```

**Traitement pour B**:
1. B reçoit 404 (fichier n'existe plus)
2. B crée le fichier comme nouveau: `POST /api/files`
3. Fichier ressuscité en version 1 (nouvelle incarnation)

**Alternative** (si on veut préserver l'historique):
1. Avertir l'utilisateur: "fichier supprimé par A, voulez-vous le recréer?"

---

### SC-12: Conflit rename concurrent

**Situation**: A renomme `a.txt` → `b.txt`, B renomme `a.txt` → `c.txt`.

```
Machine A                    Serveur                    Machine B
─────────                    ───────                    ─────────
b.txt (ex a.txt)             a.txt (v1)                 c.txt (ex a.txt)
```

**Note**: SyncAgent ne track pas les renames comme opération atomique.
Un rename = DELETE ancien + CREATE nouveau.

**Timeline**:
```
t=1:  A: DELETE a.txt, CREATE b.txt
t=2:  B: DELETE a.txt, CREATE c.txt
t=3:  A sync → a.txt supprimé, b.txt créé (v1)
t=4:  B sync → DELETE a.txt (déjà fait), CREATE c.txt (v1)
```

**Résultat**: `b.txt` et `c.txt` existent tous les deux (pas de conflit technique).

---

## Erreurs réseau

### SC-13: Perte connexion pendant upload

**Situation**: Connexion perdue au milieu d'un upload multi-chunks.

```
file.txt (10 chunks)
├── chunk 1: uploaded ✓
├── chunk 2: uploaded ✓
├── chunk 3: uploaded ✓
├── chunk 4: TIMEOUT ✗
└── chunks 5-10: not sent
```

**Traitement actuel** (à améliorer Phase 12):
1. Upload échoue, fichier reste `MODIFIED`
2. Retry au prochain sync
3. **Problème**: chunks 1-3 re-uploadés (gaspillage)

**Traitement cible (Phase 12)**:
1. Tracker chunks uploadés dans `upload_progress`
2. Au retry: vérifier quels chunks existent sur serveur
3. Reprendre à partir du chunk 4

---

### SC-14: Perte connexion pendant download

**Situation**: Connexion perdue pendant téléchargement.

```
file.txt (10 chunks)
├── chunk 1: downloaded ✓
├── chunk 2: downloaded ✓
├── chunk 3: TIMEOUT ✗
└── chunks 4-10: not received
```

**Traitement actuel**:
1. Download échoue, fichier partiellement écrit
2. Fichier corrompu si pas géré

**Traitement cible (Phase 12)**:
1. Écrire dans `file.txt.tmp`
2. Rename atomique après succès
3. Si échec: supprimer `.tmp`, retry complet
4. **Amélioration**: tracker progression pour resume

---

### SC-15: Serveur indisponible

**Situation**: Le serveur ne répond pas.

**Traitement**:
1. Toutes les requêtes échouent (timeout/connection refused)
2. Marquer le client comme `OFFLINE`
3. Continuer à tracker les changements locaux
4. Les fichiers modifiés restent `MODIFIED`
5. Au retour réseau: sync toutes les modifications accumulées

---

### SC-16: Token expiré/révoqué

**Situation**: Le token d'authentification n'est plus valide.

**Traitement**:
1. Serveur répond 401 Unauthorized
2. Afficher erreur à l'utilisateur
3. Nécessite nouveau `syncagent register`

---

## Cas limites

### SC-17: Fichier très volumineux (>1GB)

**Considérations**:
- CDC produit ~250 chunks pour 1GB (4MB average)
- Upload séquentiel = lent
- Risque de modification pendant upload

**Traitement cible**:
1. Upload parallèle (4-8 connexions)
2. Progress tracking par chunk
3. Si fichier modifié pendant upload: abandonner, recommencer

---

### SC-18: Beaucoup de petits fichiers

**Situation**: 10,000 fichiers de 1KB chacun.

**Considérations**:
- 10,000 requêtes HTTP si upload séquentiel
- Scan local: os.walk() lent

**Traitement cible (Phase 14)**:
1. Batch API pour métadonnées
2. Skip chunks < 1MB (embed dans métadonnées?)
3. Index local pour éviter full scan

---

### SC-19: Fichier modifié pendant chunk

**Situation**: Le fichier change pendant que CDC le découpe.

```
Timeline:
t=0:   chunk_file() commence
t=0.5: chunk 1 lu
t=1:   UTILISATEUR modifie le fichier
t=1.5: chunk 2 lu (contenu incohérent!)
```

**Traitement actuel**: Non géré (données potentiellement corrompues)

**Traitement cible**:
1. Lire le fichier entier en mémoire (si petit)
2. OU verrouiller le fichier pendant lecture
3. OU détecter modification (mtime changé) et abandonner

---

### SC-20: Fichier verrouillé par autre application

**Situation**: Word/Excel a le fichier ouvert.

**Traitement**:
1. Tentative d'ouverture échoue (PermissionError)
2. Marquer comme erreur temporaire
3. Retry au prochain cycle
4. Après N échecs: notifier l'utilisateur

---

### SC-21: Caractères spéciaux dans noms de fichiers

**Cas problématiques**:
- Windows interdit: `\ / : * ? " < > |`
- macOS/Linux autorisent presque tout
- Unicode, emojis, etc.

**Traitement**:
1. Normaliser les chemins (NFC normalization)
2. Rejeter/renommer les caractères interdits cross-platform
3. Avertir l'utilisateur si incompatibilité

---

### SC-22: Liens symboliques

**Situation**: Le dossier sync contient des symlinks.

**Options**:
1. **Ignorer** (traitement actuel recommandé)
2. Suivre le lien (risque de boucle, duplication)
3. Sync le lien comme fichier spécial

**Traitement recommandé**: Ignorer les symlinks (ajouter aux patterns ignorés).

---

### SC-23: Fichier `.syncignore` modifié

**Situation**: L'utilisateur ajoute un pattern à `.syncignore`.

```
Avant: *.log non ignoré → synced
Après: *.log ignoré
```

**Traitement**:
1. Nouveaux fichiers .log ignorés (pas de sync)
2. Fichiers .log déjà synced: **non supprimés du serveur**
3. L'utilisateur doit supprimer manuellement si voulu

---

## Matrice de décision

### Push (Local → Serveur)

| État Local | Fichier Serveur | Action |
|------------|-----------------|--------|
| `NEW` | N'existe pas | `POST /api/files` → créer |
| `NEW` | Existe | Conflit: comparer hash |
| `MODIFIED` | Même version | `PUT /api/files` → update |
| `MODIFIED` | Version différente | Conflit: comparer hash |
| `DELETED` | Existe | `DELETE /api/files` |
| `DELETED` | N'existe pas | Supprimer de DB locale |
| `SYNCED` | - | Rien à faire |
| `CONFLICT` | - | Attendre résolution user |

### Pull (Serveur → Local)

| État Local | Version Serveur | Action |
|------------|-----------------|--------|
| N'existe pas | Existe | Télécharger |
| `SYNCED` | Plus récente | Télécharger, écraser |
| `SYNCED` | Même | Rien |
| `SYNCED` | Supprimé | Supprimer local |
| `MODIFIED` | Plus récente | **CONFLIT** |
| `MODIFIED` | Supprimé | Recréer sur serveur |
| `NEW` | Existe | **CONFLIT** |
| `DELETED` | Plus récente | Recréer local? ou ignorer? |

### Résolution de conflit

| Hash Local | Hash Serveur | Action |
|------------|--------------|--------|
| Identique | Identique | Faux conflit → SYNCED |
| Différent | Différent | Vrai conflit → `.conflict-*` |

---

## Diagramme de flux complet

```
                    ┌─────────────────┐
                    │   SYNC START    │
                    └────────┬────────┘
                             │
              ┌──────────────┴──────────────┐
              ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │  SCAN LOCAL     │           │   FETCH SERVER  │
    │  CHANGES        │           │   FILE LIST     │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             ▼                             ▼
    ┌─────────────────┐           ┌─────────────────┐
    │  Mark files:    │           │  Compare with   │
    │  NEW/MODIFIED/  │           │  local state    │
    │  DELETED        │           │                 │
    └────────┬────────┘           └────────┬────────┘
             │                             │
             └──────────────┬──────────────┘
                            │
                            ▼
                 ┌─────────────────────┐
                 │    PUSH CHANGES     │
                 │    (Local→Server)   │
                 └──────────┬──────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    ┌─────────┐       ┌──────────┐       ┌──────────┐
    │   NEW   │       │ MODIFIED │       │ DELETED  │
    │  files  │       │  files   │       │  files   │
    └────┬────┘       └────┬─────┘       └────┬─────┘
         │                 │                  │
         ▼                 ▼                  ▼
    POST /files      PUT /files         DELETE /files
         │                 │                  │
         ├─────── 409? ────┤                  │
         ▼                 ▼                  │
    ┌──────────────────────────┐              │
    │   CONFLICT RESOLUTION    │              │
    │   - Compare hashes       │              │
    │   - Create .conflict-*   │              │
    │   - Download server ver  │              │
    └──────────────────────────┘              │
                            │                 │
                            └────────┬────────┘
                                     │
                                     ▼
                 ┌─────────────────────┐
                 │    PULL CHANGES     │
                 │    (Server→Local)   │
                 └──────────┬──────────┘
                            │
         ┌──────────────────┼──────────────────┐
         ▼                  ▼                  ▼
    ┌─────────┐       ┌──────────┐       ┌──────────┐
    │   NEW   │       │ UPDATED  │       │ DELETED  │
    │  server │       │  server  │       │  server  │
    └────┬────┘       └────┬─────┘       └────┬─────┘
         │                 │                  │
         ▼                 ▼                  ▼
    Download &       Download &          Delete local
    create local     overwrite local     (if SYNCED)
         │                 │                  │
         └────────────────┬───────────────────┘
                          │
                          ▼
                 ┌─────────────────┐
                 │   SYNC COMPLETE │
                 └─────────────────┘
```

---

## Améliorations prévues

### Phase 12: Resume Sync
- [ ] Table `upload_progress` pour tracker chunks uploadés
- [ ] Écriture atomique (`.tmp` → rename)
- [ ] Retry avec backoff exponentiel

### Phase 14: Optimizations
- [ ] API `/api/changes?since=timestamp` (éviter poll complet)
- [ ] Delta sync (ne transférer que les blocs modifiés)
- [ ] Parallel uploads/downloads

### Phase 15: Real-Time
- [ ] WebSocket pour push notifications serveur→client
- [ ] Events temps réel dans la WebUI
