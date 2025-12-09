# Architecture Zero-Knowledge E2EE

## Vue d'ensemble

```
+-------------------------------------------------------------+
|                         BLOCK STORAGE                        |
|                     (OVH S3 / Swift / Ceph)                  |
+-------------------------------------------------------------+
|  Blocs chiffrés uniquement - illisibles sans clé client      |
|  /{user_id}/{chunk_hash}.enc                                 |
+-------------------------------------------------------------+
                              ^
                              | HTTPS (blocs chiffrés)
                              |
+-------------------------------------------------------------+
|                      SERVEUR MÉTADONNÉES                     |
|                    (FastAPI + SQLite WAL)                    |
+-------------------------------------------------------------+
|  NE STOCKE QUE :                                             |
|  - Arborescence des fichiers                                 |
|  - Hash des blocs (pas le contenu)                           |
|  - Versions et branches                                      |
|  - Conflits détectés                                         |
|  - Métadonnées machines                                      |
|                                                              |
|  NE VOIT JAMAIS :                                            |
|  - Le contenu des fichiers                                   |
|  - Les clés de chiffrement                                   |
|  - Les blocs déchiffrés                                      |
+-------------------------------------------------------------+
                              ^
                              | HTTPS (métadonnées + blocs chiffrés)
                              |
+-------------------------------------------------------------+
|                       CLIENT LOCAL                           |
+-------------------------------------------------------------+
|  SEUL ENDROIT OÙ :                                           |
|  - Les fichiers sont en clair                                |
|  - Le chiffrement/déchiffrement a lieu                       |
|  - La clé E2EE existe                                        |
|                                                              |
|  Composants :                                                |
|  - File watcher (watchdog)                                   |
|  - Moteur de chiffrement (AES-GCM)                           |
|  - Content-Defined Chunking (CDC)                            |
|  - SQLite local                                              |
|  - Tray icon (pystray)                                       |
|  - Protocol handler (syncfile://)                            |
+-------------------------------------------------------------+
```

## Modèle de Sécurité

### Séparation des clés

| Clé | Usage | Permet |
|-----|-------|--------|
| Token Auth (HTTPS API) | Authentifie le client | Upload blocs, Modifier meta, Supprimer |
| Clé E2EE (locale) | Chiffre les données | Lire/Écrire fichiers |

### Scénarios de compromission

| Attaque | Conséquence |
|---------|-------------|
| Vol du token seul | Accès aux blocs CHIFFRÉS (inutiles) |
| Vol de la clé seule | Impossible d'accéder au serveur |
| Vol des deux | Compromission (nécessite accès physique) |
| Hack du serveur | RIEN (Zero Knowledge) |
| Hack du storage OVH | RIEN (blocs chiffrés) |

## Stack Technique

| Composant | Technologie |
|-----------|-------------|
| Client | Python 3.11+ |
| Crypto | cryptography (AES-GCM), argon2-cffi |
| File watcher | watchdog |
| HTTP client | httpx |
| DB locale | SQLite |
| Tray icon | pystray + Pillow |
| Serveur | FastAPI + Jinja2 + HTMX |
| CSS | Pico CSS |
| DB serveur | SQLite WAL |
| Block storage | OVH S3 (boto3) |
