# API REST

## Endpoints

### Authentification

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `POST` | `/api/auth/register` | Enregistre une machine (token retourné) |
| `POST` | `/api/auth/check-name` | Vérifie disponibilité nom machine |

### Fichiers

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/files` | Liste les fichiers (métadonnées) |
| `GET` | `/api/files/{id}/versions` | Versions d'un fichier |
| `POST` | `/api/files` | Crée/modifie un fichier (metadata) |
| `DELETE` | `/api/files/{id}` | Supprime (tombstone) |

### Chunks

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/chunks/{hash}` | Télécharge un bloc chiffré |
| `POST` | `/api/chunks` | Upload un bloc chiffré |
| `HEAD` | `/api/chunks/{hash}` | Vérifie si bloc existe |

### Conflits

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/conflicts` | Liste les conflits |
| `POST` | `/api/conflicts/{id}/resolve` | Résout un conflit |

### Corbeille

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/trash` | Liste fichiers supprimés |
| `POST` | `/api/trash/{id}/restore` | Restaure un fichier |
| `DELETE` | `/api/trash/{id}` | Supprime définitivement |

### Invitations (admin)

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/invitations` | Liste invitations |
| `POST` | `/api/invitations` | Crée une invitation |
| `DELETE` | `/api/invitations/{id}` | Révoque une invitation |

### Autres

| Méthode | Endpoint | Description |
|---------|----------|-------------|
| `GET` | `/api/status` | État des machines |
| `GET` | `/api/changes?since=<ts>` | Changements depuis timestamp |
| `GET` | `/api/machines` | Liste des machines |

## WebSocket

Endpoint: `/ws`

### Messages Serveur → Client

```json
{"type": "file_updated", "file_id": 123, "path": "/docs/file.pdf", "version_id": "uuid", "machine": "laptop"}
{"type": "file_deleted", "file_id": 123, "path": "/docs/old.pdf", "deleted_by": "laptop"}
{"type": "conflict_detected", "file_id": 123, "branches": [...]}
{"type": "machine_online", "machine_id": "uuid", "name": "laptop"}
{"type": "machine_offline", "machine_id": "uuid", "name": "laptop"}
{"type": "pong"}
```

### Messages Client → Serveur

```json
{"type": "ping"}
```

## Authentification

- **Machines**: Bearer token (`Authorization: Bearer <token>`)
- **Web UI**: Session cookie (HttpOnly, Secure, SameSite=Strict)
