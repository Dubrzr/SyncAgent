# Spec : Réorganisation du Code Sync

## Objectif

Extraire les règles métier et concepts domaine dans des modules dédiés pour :
- Faciliter la compréhension du code
- Améliorer la testabilité
- Réduire le couplage entre modules
- Permettre une maintenance plus sûre

## État Actuel : Problèmes Identifiés

### 1. Logique Métier Éparpillée

| Concept | Fichiers Concernés | Problème |
|---------|-------------------|----------|
| **Conflits** | `conflict.py`, `upload_worker.py`, `download_worker.py`, `coordinator.py`, `types.py` | 5+ fichiers, 3+ phases (pre/mid/post) |
| **Priorités** | `types.py` (définition), `queue.py` (usage) | Sémantique split |
| **Versions** | `change_scanner.py`, `coordinator.py`, `workers/*`, `types.py` | 5+ emplacements |
| **États** | `TransferState`, `WorkerState`, `TransferStatus`, `PoolState` | 4 enums similaires |
| **Décisions** | `coordinator.py` | if/elif procédural, non déclaratif |

### 2. Duplications

```
TransferStatus.COMPLETED  ≈  WorkerState.COMPLETED
TransferStatus.CANCELLED  ≈  WorkerState.CANCELLED
BaseWorker._cancel_requested  ≈  WorkerTask.cancel_requested
TransferState.base_version  ≈  event.metadata["parent_version"]
```

### 3. Couplage Fort

```
coordinator.py → types.py (6 imports)
              → workers/base.py (état)
              → workers/transfers/conflict.py (résolution)
              → queue.py (événements)
```

---

## Architecture Cible : Domain Modules

### Structure Proposée

```
src/syncagent/client/sync/
├── __init__.py              # Re-exports publics
├── types.py                 # Types de base (SyncEvent, etc.)
│
├── domain/                  # ★ NOUVEAU - Règles métier
│   ├── __init__.py
│   ├── priorities.py        # Logique de priorité des événements
│   ├── conflicts.py         # Détection et résolution de conflits
│   ├── decisions.py         # Matrice de décision (concurrent events)
│   ├── versions.py          # Gestion des versions serveur/local
│   └── transfers.py         # États et transitions de transfert
│
├── queue.py                 # EventQueue (simplifié)
├── coordinator.py           # Orchestrateur (simplifié)
├── change_scanner.py        # Scanner (utilise domain/)
├── watcher.py               # FileWatcher (inchangé)
├── ignore.py                # IgnorePatterns (inchangé)
├── retry.py                 # Retry logic (inchangé)
│
└── workers/
    ├── __init__.py
    ├── base.py              # BaseWorker (simplifié)
    ├── pool.py              # WorkerPool
    ├── upload_worker.py     # Utilise domain/conflicts
    ├── download_worker.py   # Utilise domain/conflicts
    ├── delete_worker.py     # Inchangé
    └── transfers/
        ├── __init__.py
        ├── file_uploader.py
        └── file_downloader.py
```

---

## Module 1 : `domain/priorities.py`

### Responsabilité
Centraliser toute la logique de priorité et d'ordonnancement des événements.

### Interface

```python
"""Event priority and ordering logic.

This module defines:
- Priority levels for sync events
- Ordering rules for queue processing
- Deduplication strategy (mtime-aware)
"""

from dataclasses import dataclass
from enum import IntEnum
from typing import Protocol


class Priority(IntEnum):
    """Event priority levels (lower = higher priority)."""

    CRITICAL = 10      # Deletions - avoid useless transfers
    HIGH = 20          # Local changes - user's work
    NORMAL = 30        # Remote changes - other machines
    LOW = 90           # Internal events - transfer results


@dataclass(frozen=True)
class PriorityRule:
    """Maps event type to priority level."""

    event_type: str
    priority: Priority
    reason: str


# Declarative priority rules
PRIORITY_RULES: list[PriorityRule] = [
    PriorityRule("LOCAL_DELETED", Priority.CRITICAL, "Avoid uploading then deleting"),
    PriorityRule("REMOTE_DELETED", Priority.CRITICAL, "Clean up local quickly"),
    PriorityRule("LOCAL_CREATED", Priority.HIGH, "User created file"),
    PriorityRule("LOCAL_MODIFIED", Priority.HIGH, "User modified file"),
    PriorityRule("REMOTE_CREATED", Priority.NORMAL, "Download new remote file"),
    PriorityRule("REMOTE_MODIFIED", Priority.NORMAL, "Download remote changes"),
    PriorityRule("TRANSFER_COMPLETE", Priority.LOW, "Internal bookkeeping"),
    PriorityRule("TRANSFER_FAILED", Priority.LOW, "Internal bookkeeping"),
]


class EventComparator(Protocol):
    """Protocol for comparing events for deduplication."""

    def should_replace(self, old_event: "SyncEvent", new_event: "SyncEvent") -> bool:
        """Return True if new_event should replace old_event."""
        ...


class MtimeAwareComparator:
    """Compares events by file mtime, falls back to event timestamp.

    This ensures that if a file is modified during a scan:
    - The watcher's event (with current mtime) wins
    - The scanner's event (with stale mtime) is ignored
    """

    def should_replace(self, old_event: "SyncEvent", new_event: "SyncEvent") -> bool:
        old_mtime = old_event.metadata.get("mtime")
        new_mtime = new_event.metadata.get("mtime")

        if old_mtime is not None and new_mtime is not None:
            if new_mtime < old_mtime:
                return False  # Keep old (more recent file state)
            if new_mtime == old_mtime:
                return new_event.timestamp > old_event.timestamp

        return True  # Default: new replaces old


def get_priority(event_type: str) -> Priority:
    """Get priority for an event type."""
    for rule in PRIORITY_RULES:
        if rule.event_type == event_type:
            return rule.priority
    return Priority.NORMAL


def get_priority_reason(event_type: str) -> str:
    """Get the reason why an event type has its priority."""
    for rule in PRIORITY_RULES:
        if rule.event_type == event_type:
            return rule.reason
    return "Default priority"
```

### Avantages
- Priorités définies de manière déclarative avec raisons
- Comparateur découplé de la queue
- Facile à tester unitairement
- Facile d'ajouter de nouvelles règles

---

## Module 2 : `domain/conflicts.py`

### Responsabilité
Centraliser toute la logique de détection et résolution de conflits.

### Interface

```python
"""Conflict detection and resolution.

Implements "Server Wins + Local Preserved" strategy:
1. Server version is always downloaded
2. Local changes are preserved as .conflict-* files
3. User decides manually which version to keep

Conflict scenarios:
- Upload conflict: Server changed while uploading
- Download conflict: Local changed after scan, before download
- Concurrent conflict: Remote event while transfer in progress
"""

from dataclasses import dataclass
from enum import Enum, auto
from pathlib import Path
from typing import Protocol


class ConflictType(Enum):
    """When the conflict was detected."""

    PRE_TRANSFER = auto()      # Before transfer started (version check)
    MID_TRANSFER = auto()      # During transfer (periodic check)
    POST_TRANSFER = auto()     # At commit time (VERSION_CONFLICT)
    CONCURRENT_EVENT = auto()  # New event while transfer in progress


class ConflictOutcome(Enum):
    """Result of conflict detection/resolution."""

    NO_CONFLICT = auto()       # Safe to proceed
    ALREADY_SYNCED = auto()    # Same content, no real conflict
    RESOLVED = auto()          # Local renamed, proceed with transfer
    RETRY_NEEDED = auto()      # Race condition, need to retry
    ABORT = auto()             # Cannot resolve, abort transfer


@dataclass
class ConflictContext:
    """All information needed to detect/resolve a conflict."""

    local_path: Path
    relative_path: str
    local_mtime: float | None
    local_size: int | None
    local_hash: str | None
    server_version: int | None
    server_hash: str | None
    expected_version: int | None  # Version we're working against


@dataclass
class ConflictResolution:
    """Result of conflict resolution."""

    outcome: ConflictOutcome
    conflict_path: Path | None = None    # Path to .conflict-* file
    server_version: int | None = None    # New server version after resolution
    message: str = ""                    # Human-readable explanation


class ConflictDetector(Protocol):
    """Protocol for detecting conflicts."""

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        """Check if there's a conflict. Does not modify anything."""
        ...


class ConflictResolver(Protocol):
    """Protocol for resolving conflicts."""

    def resolve(self, ctx: ConflictContext) -> ConflictResolution:
        """Resolve a conflict. May rename files, download server version."""
        ...


# === Implementations ===

class PreDownloadConflictDetector:
    """Detects conflicts before a download overwrites local file.

    Scenarios:
    1. Local file exists but untracked → conflict (appeared after scan)
    2. Local file modified since last sync → conflict
    3. Local matches tracked state → no conflict
    """

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        if not ctx.local_path.exists():
            return ConflictOutcome.NO_CONFLICT

        if ctx.local_mtime is None:
            # Untracked file appeared
            return ConflictOutcome.RESOLVED  # Will need resolution

        current = ctx.local_path.stat()
        if current.st_mtime > ctx.local_mtime or current.st_size != ctx.local_size:
            return ConflictOutcome.RESOLVED  # Modified, needs resolution

        return ConflictOutcome.NO_CONFLICT


class PreUploadConflictDetector:
    """Detects conflicts before upload by checking server version.

    If server version != expected version, someone else modified the file.
    """

    def __init__(self, client: "HTTPClient"):
        self._client = client

    def check(self, ctx: ConflictContext) -> ConflictOutcome:
        if ctx.expected_version is None:
            return ConflictOutcome.NO_CONFLICT  # New file

        try:
            server_file = self._client.get_file_metadata(ctx.relative_path)
            if server_file.version != ctx.expected_version:
                return ConflictOutcome.RESOLVED  # Version mismatch
        except NotFoundError:
            return ConflictOutcome.RESOLVED  # File deleted on server

        return ConflictOutcome.NO_CONFLICT


class ServerWinsResolver:
    """Resolves conflicts with "Server Wins + Local Preserved" strategy.

    1. Compare local hash with server hash
    2. If same → no real conflict, mark as synced
    3. If different → rename local to .conflict-*, download server version
    """

    def __init__(self, client: "HTTPClient", encryption_key: bytes):
        self._client = client
        self._key = encryption_key

    def resolve(self, ctx: ConflictContext) -> ConflictResolution:
        # Get server file info
        server_file = self._client.get_file_metadata(ctx.relative_path)

        # Compare hashes
        if ctx.local_hash == server_file.content_hash:
            return ConflictResolution(
                outcome=ConflictOutcome.ALREADY_SYNCED,
                server_version=server_file.version,
                message="Same content, no real conflict",
            )

        # Real conflict - rename local file
        conflict_path = generate_conflict_filename(ctx.local_path)
        try:
            safe_rename(ctx.local_path, conflict_path)
        except RaceConditionError:
            return ConflictResolution(
                outcome=ConflictOutcome.RETRY_NEEDED,
                message="File modified during rename",
            )

        # Download server version
        downloader = FileDownloader(self._client, self._key)
        downloader.download_file(server_file, ctx.local_path)

        return ConflictResolution(
            outcome=ConflictOutcome.RESOLVED,
            conflict_path=conflict_path,
            server_version=server_file.version,
            message=f"Local saved as {conflict_path.name}",
        )


# === Utility functions ===

def generate_conflict_filename(path: Path, machine_name: str | None = None) -> Path:
    """Generate a conflict filename: name.conflict-YYYYMMDD-HHMMSS-machine.ext"""
    from datetime import datetime

    machine = machine_name or get_machine_name()
    now = datetime.now()
    timestamp = now.strftime("%Y%m%d-%H%M%S") + f"{now.microsecond // 1000:03d}"

    return path.parent / f"{path.stem}.conflict-{timestamp}-{machine}{path.suffix}"


def safe_rename(src: Path, dst: Path) -> None:
    """Rename with race condition detection."""
    mtime_before = src.stat().st_mtime
    src.rename(dst)
    mtime_after = dst.stat().st_mtime

    if mtime_after != mtime_before:
        dst.rename(src)  # Rollback
        raise RaceConditionError(f"File {src} modified during rename")


class RaceConditionError(Exception):
    """Raised when a file is modified during conflict resolution."""
    pass
```

### Avantages
- Séparation détection / résolution
- Stratégies interchangeables (Protocol)
- Contexte explicite (ConflictContext)
- Testable en isolation

---

## Module 3 : `domain/decisions.py`

### Responsabilité
Définir la matrice de décision pour les événements concurrents.

### Interface

```python
"""Decision matrix for concurrent events.

When a new event arrives while a transfer is in progress,
this module decides what action to take.

Matrix:
| New Event       | In Progress | Action                    |
|-----------------|-------------|---------------------------|
| LOCAL_MODIFIED  | DOWNLOAD    | Cancel download, upload   |
| LOCAL_DELETED   | DOWNLOAD    | Cancel download, delete   |
| REMOTE_MODIFIED | UPLOAD      | Mark conflict, continue   |
| REMOTE_DELETED  | UPLOAD      | Conflict-copy, continue   |
| *               | same type   | Ignore (already handling) |
"""

from dataclasses import dataclass
from enum import Enum, auto
from typing import Callable


class DecisionAction(Enum):
    """Action to take on concurrent event."""

    IGNORE = auto()              # Already handling this path
    CANCEL_AND_REQUEUE = auto()  # Cancel current, queue new
    MARK_CONFLICT = auto()       # Continue but flag potential conflict
    CREATE_CONFLICT_COPY = auto()  # Save local before overwrite


@dataclass(frozen=True)
class DecisionRule:
    """A rule in the decision matrix."""

    new_event_source: str        # "LOCAL" or "REMOTE"
    new_event_type: str | None   # Specific type or None for any
    existing_transfer: str       # "UPLOAD", "DOWNLOAD", or "DELETE"
    action: DecisionAction
    reason: str


# Declarative decision rules
DECISION_RULES: list[DecisionRule] = [
    # Local events during download → cancel download, handle local
    DecisionRule(
        new_event_source="LOCAL",
        new_event_type=None,  # Any local event
        existing_transfer="DOWNLOAD",
        action=DecisionAction.CANCEL_AND_REQUEUE,
        reason="Local change takes precedence over incoming remote",
    ),

    # Remote modified during upload → potential conflict
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type="REMOTE_MODIFIED",
        existing_transfer="UPLOAD",
        action=DecisionAction.MARK_CONFLICT,
        reason="Server changed while uploading, may conflict at commit",
    ),

    # Remote deleted during upload → create conflict copy
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type="REMOTE_DELETED",
        existing_transfer="UPLOAD",
        action=DecisionAction.CREATE_CONFLICT_COPY,
        reason="Server deleted, but user has local changes to preserve",
    ),

    # Remote events during download → ignore
    DecisionRule(
        new_event_source="REMOTE",
        new_event_type=None,
        existing_transfer="DOWNLOAD",
        action=DecisionAction.IGNORE,
        reason="Already downloading latest from server",
    ),

    # Local events during upload → ignore
    DecisionRule(
        new_event_source="LOCAL",
        new_event_type=None,
        existing_transfer="UPLOAD",
        action=DecisionAction.IGNORE,
        reason="Already uploading local changes",
    ),
]


class DecisionMatrix:
    """Evaluates decision rules for concurrent events."""

    def __init__(self, rules: list[DecisionRule] | None = None):
        self._rules = rules or DECISION_RULES

    def evaluate(
        self,
        new_event_source: str,
        new_event_type: str,
        existing_transfer_type: str,
    ) -> tuple[DecisionAction, str]:
        """Evaluate rules and return action with reason.

        Returns:
            (action, reason) tuple
        """
        for rule in self._rules:
            if self._matches(rule, new_event_source, new_event_type, existing_transfer_type):
                return rule.action, rule.reason

        # Default: ignore unknown combinations
        return DecisionAction.IGNORE, "No matching rule, ignoring"

    def _matches(
        self,
        rule: DecisionRule,
        source: str,
        event_type: str,
        transfer_type: str,
    ) -> bool:
        if rule.new_event_source != source:
            return False
        if rule.existing_transfer != transfer_type:
            return False
        if rule.new_event_type is not None and rule.new_event_type != event_type:
            return False
        return True


# Convenience function
def decide(new_event: "SyncEvent", existing_transfer: "TransferState") -> DecisionAction:
    """Quick decision lookup."""
    matrix = DecisionMatrix()
    action, _ = matrix.evaluate(
        new_event_source=new_event.source.name,
        new_event_type=new_event.event_type.name,
        existing_transfer_type=existing_transfer.transfer_type.name,
    )
    return action
```

### Avantages
- Règles déclaratives, pas procédurales
- Raisons documentées pour chaque règle
- Facile d'ajouter/modifier des règles
- Entièrement testable

---

## Module 4 : `domain/versions.py`

### Responsabilité
Centraliser la gestion des versions serveur/local.

### Interface

```python
"""Version tracking and comparison.

Tracks:
- server_version: Version counter from server (increments on each change)
- local state: mtime/size when we last synced

Version rules:
- New file: version = None (will be assigned by server)
- Update: must provide parent_version (optimistic locking)
- Conflict: server_version != expected parent_version
"""

from dataclasses import dataclass
from typing import Protocol


@dataclass
class VersionInfo:
    """Version information for a file."""

    server_version: int | None     # None = new file
    local_mtime: float | None      # When we last synced
    local_size: int | None         # Size when we last synced
    chunk_hashes: list[str] | None  # Content hashes


class VersionStore(Protocol):
    """Protocol for storing/retrieving version info."""

    def get(self, path: str) -> VersionInfo | None:
        """Get version info for a path."""
        ...

    def set(self, path: str, info: VersionInfo) -> None:
        """Store version info for a path."""
        ...

    def delete(self, path: str) -> None:
        """Remove version info for a path."""
        ...


class VersionChecker:
    """Checks version consistency."""

    def __init__(self, store: VersionStore):
        self._store = store

    def is_locally_modified(self, path: str, current_mtime: float, current_size: int) -> bool:
        """Check if local file was modified since last sync."""
        info = self._store.get(path)
        if info is None:
            return True  # New file = "modified"

        return (
            current_mtime > (info.local_mtime or 0)
            or current_size != info.local_size
        )

    def get_parent_version(self, path: str) -> int | None:
        """Get version to use as parent for update."""
        info = self._store.get(path)
        return info.server_version if info else None

    def needs_download(self, path: str, server_version: int) -> bool:
        """Check if server version is newer than what we have."""
        info = self._store.get(path)
        if info is None:
            return True  # Don't have it

        return server_version > (info.server_version or 0)


class VersionUpdater:
    """Updates version store after sync operations."""

    def __init__(self, store: VersionStore):
        self._store = store

    def mark_synced(
        self,
        path: str,
        server_version: int,
        local_mtime: float,
        local_size: int,
        chunk_hashes: list[str] | None = None,
    ) -> None:
        """Record successful sync."""
        self._store.set(path, VersionInfo(
            server_version=server_version,
            local_mtime=local_mtime,
            local_size=local_size,
            chunk_hashes=chunk_hashes,
        ))

    def mark_deleted(self, path: str) -> None:
        """Record file deletion."""
        self._store.delete(path)
```

### Avantages
- Interface claire (VersionStore Protocol)
- Séparation vérification / mise à jour
- Logique de comparaison centralisée
- Découplé du stockage (SQLite, memory, etc.)

---

## Module 5 : `domain/transfers.py`

### Responsabilité
Définir les états et transitions des transferts.

### Interface

```python
"""Transfer state machine.

States:
    PENDING → IN_PROGRESS → COMPLETED
                         → CANCELLED
                         → FAILED

All state transitions are validated.
"""

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Callable


class TransferType(Enum):
    """Type of transfer operation."""
    UPLOAD = auto()
    DOWNLOAD = auto()
    DELETE = auto()


class TransferStatus(Enum):
    """Status of a transfer."""
    PENDING = auto()
    IN_PROGRESS = auto()
    COMPLETED = auto()
    CANCELLED = auto()
    FAILED = auto()


# Valid state transitions
VALID_TRANSITIONS: dict[TransferStatus, set[TransferStatus]] = {
    TransferStatus.PENDING: {TransferStatus.IN_PROGRESS, TransferStatus.CANCELLED},
    TransferStatus.IN_PROGRESS: {TransferStatus.COMPLETED, TransferStatus.CANCELLED, TransferStatus.FAILED},
    TransferStatus.COMPLETED: set(),  # Terminal
    TransferStatus.CANCELLED: set(),  # Terminal
    TransferStatus.FAILED: set(),     # Terminal
}


class InvalidTransitionError(Exception):
    """Raised when attempting invalid state transition."""
    pass


@dataclass
class Transfer:
    """A tracked transfer operation."""

    path: str
    transfer_type: TransferType
    status: TransferStatus = TransferStatus.PENDING

    # Version tracking (for conflict detection)
    base_version: int | None = None
    detected_server_version: int | None = None

    # Conflict info
    has_conflict: bool = False
    conflict_type: str | None = None

    # Callbacks
    _on_complete: Callable[["Transfer"], None] | None = field(default=None, repr=False)
    _on_error: Callable[["Transfer", Exception], None] | None = field(default=None, repr=False)

    def transition_to(self, new_status: TransferStatus) -> None:
        """Transition to a new status with validation."""
        if new_status not in VALID_TRANSITIONS[self.status]:
            raise InvalidTransitionError(
                f"Cannot transition from {self.status.name} to {new_status.name}"
            )
        self.status = new_status

    def start(self) -> None:
        """Mark transfer as started."""
        self.transition_to(TransferStatus.IN_PROGRESS)

    def complete(self) -> None:
        """Mark transfer as completed."""
        self.transition_to(TransferStatus.COMPLETED)
        if self._on_complete:
            self._on_complete(self)

    def cancel(self) -> None:
        """Mark transfer as cancelled."""
        if self.status in (TransferStatus.PENDING, TransferStatus.IN_PROGRESS):
            self.transition_to(TransferStatus.CANCELLED)

    def fail(self, error: Exception) -> None:
        """Mark transfer as failed."""
        self.transition_to(TransferStatus.FAILED)
        if self._on_error:
            self._on_error(self, error)

    def mark_conflict(self, conflict_type: str, server_version: int) -> None:
        """Flag potential conflict."""
        self.has_conflict = True
        self.conflict_type = conflict_type
        self.detected_server_version = server_version

    @property
    def is_terminal(self) -> bool:
        """Check if transfer is in a terminal state."""
        return self.status in (
            TransferStatus.COMPLETED,
            TransferStatus.CANCELLED,
            TransferStatus.FAILED,
        )


class TransferTracker:
    """Tracks active transfers by path."""

    def __init__(self):
        self._transfers: dict[str, Transfer] = {}

    def create(
        self,
        path: str,
        transfer_type: TransferType,
        base_version: int | None = None,
    ) -> Transfer:
        """Create and track a new transfer."""
        transfer = Transfer(
            path=path,
            transfer_type=transfer_type,
            base_version=base_version,
        )
        self._transfers[path] = transfer
        return transfer

    def get(self, path: str) -> Transfer | None:
        """Get transfer for path."""
        return self._transfers.get(path)

    def get_active(self, path: str) -> Transfer | None:
        """Get transfer only if not terminal."""
        transfer = self._transfers.get(path)
        if transfer and not transfer.is_terminal:
            return transfer
        return None

    def remove(self, path: str) -> None:
        """Remove transfer from tracking."""
        self._transfers.pop(path, None)

    def all_active(self) -> list[Transfer]:
        """Get all non-terminal transfers."""
        return [t for t in self._transfers.values() if not t.is_terminal]

    def cancel_all(self) -> None:
        """Cancel all active transfers."""
        for transfer in self.all_active():
            transfer.cancel()
```

### Avantages
- Machine à états explicite avec validation
- Transitions documentées
- Callbacks intégrés
- Tracker centralisé

---

## Plan de Migration

### Phase 1 : Créer `domain/` sans casser l'existant

1. Créer `domain/__init__.py`
2. Créer chaque module avec les nouvelles interfaces
3. Exporter depuis `domain/__init__.py`

### Phase 2 : Migrer progressivement

| Module Source | → | Module Domain |
|--------------|---|---------------|
| `types.py` (SyncEventType values) | → | `domain/priorities.py` |
| `queue.py` (deduplication) | → | `domain/priorities.py` (MtimeAwareComparator) |
| `workers/transfers/conflict.py` | → | `domain/conflicts.py` |
| `coordinator.py` (_handle_concurrent) | → | `domain/decisions.py` |
| `change_scanner.py` (version logic) | → | `domain/versions.py` |
| `types.py` (TransferState) | → | `domain/transfers.py` |

### Phase 3 : Simplifier les consommateurs

```python
# Avant (coordinator.py)
if event.source == SyncEventSource.LOCAL:
    if existing.transfer_type == TransferType.DOWNLOAD:
        # Cancel download, requeue upload
        ...
    elif existing.transfer_type == TransferType.UPLOAD:
        # Ignore
        ...

# Après
from syncagent.client.sync.domain import DecisionMatrix, DecisionAction

action = DecisionMatrix().evaluate(event, existing)
if action == DecisionAction.CANCEL_AND_REQUEUE:
    self._cancel_transfer(path)
    self._dispatch(event)
elif action == DecisionAction.MARK_CONFLICT:
    existing.mark_conflict(...)
```

### Phase 4 : Supprimer le code dupliqué

- Retirer les enums dupliqués (`WorkerState` vs `TransferStatus`)
- Retirer les flags dupliqués (`_cancel_requested` à deux niveaux)
- Consolider les statistiques

---

## Tests Requis

### Pour chaque module domain/

```
tests/client/sync/domain/
├── test_priorities.py
│   - test_priority_order
│   - test_mtime_comparator_newer_wins
│   - test_mtime_comparator_older_ignored
│   - test_mtime_comparator_same_mtime_fallback
│
├── test_conflicts.py
│   - test_pre_download_conflict_untracked_file
│   - test_pre_download_conflict_modified_file
│   - test_pre_download_no_conflict
│   - test_pre_upload_conflict_version_mismatch
│   - test_server_wins_resolver_same_hash
│   - test_server_wins_resolver_different_hash
│   - test_safe_rename_race_condition
│
├── test_decisions.py
│   - test_local_during_download_cancels
│   - test_remote_during_upload_marks_conflict
│   - test_remote_during_download_ignored
│   - test_custom_rules
│
├── test_versions.py
│   - test_is_locally_modified
│   - test_get_parent_version
│   - test_needs_download
│   - test_mark_synced
│
└── test_transfers.py
    - test_valid_transitions
    - test_invalid_transition_raises
    - test_terminal_states
    - test_cancel_all
    - test_callbacks
```

---

## Métriques de Succès

| Métrique | Avant | Après (Cible) |
|----------|-------|---------------|
| Fichiers avec logique conflit | 5+ | 1 (`domain/conflicts.py`) |
| Fichiers avec logique priorité | 2 | 1 (`domain/priorities.py`) |
| Enums d'état dupliqués | 4 | 2 |
| LOC dans `coordinator.py` | ~500 | ~300 |
| Tests unitaires domaine | 0 | 30+ |
| Couverture règles métier | Implicite | Déclarative |

---

## Conclusion

Cette réorganisation apporte :

1. **Clarté** : Chaque règle métier dans un module dédié
2. **Testabilité** : Logique découplée, testable en isolation
3. **Maintenabilité** : Modifications localisées, moins de risque de régression
4. **Documentation** : Règles déclaratives = documentation vivante
5. **Extensibilité** : Ajouter une règle = ajouter à une liste, pas modifier du code

La migration peut se faire progressivement sans casser l'existant, en commençant par les modules les plus "autonomes" (`priorities.py`, `decisions.py`).
