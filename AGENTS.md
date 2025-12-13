Rules for AI Agents :

* Never forget to make code that follow best pratices, standards and recommended architectures, think SOLID, YAGNI, KISS, DRY, Clean archi, DDD...
* Never forget to commit frequently and follow conventional commit
* You might be working in parrallel with an other agent or human, so take care to only commit your modifications, I will make sure (Julien) that everybody is not conflicting on their work by giving everyone very separate tasks
* To speed up things, only run tests related to what you modified instead of all tests during dev, and before committing you can run all unit tests for example

When you have zero context, start by reading the README.md, docs/* and TODO.md to see where we are on this project, explore code if necessary

## Spec-Driven Development

### Specs in `docs/`

All feature specifications live in `docs/` as Markdown files. Code and tests reference these specs instead of duplicating documentation.

```
docs/
├── cli/
│   ├── init.md      # Spec for 'syncagent init' command
│   ├── register.md  # Spec for 'syncagent register' command
│   ├── sync.md      # Spec for 'syncagent sync' command
│   └── server.md    # Spec for 'syncagent server' command
└── ...
```

### Code points to specs

At the top of implementation files, reference the spec:

```python
"""Server command for SyncAgent CLI.

Spec: docs/cli/server.md
"""
```

### Tests: scenarios first, then implementation

Test files should:
1. Reference the spec at the top
2. List all test scenarios as a checklist in comments
3. Implement tests after scenarios are defined

```python
"""Tests for 'syncagent register' command.

Spec: docs/cli/register.md

Test Scenarios:
---------------

register:
    - [x] Succeeds with valid invitation token
    - [x] Saves server_url, auth_token, machine_name in config
    - [x] Fails if not initialized
    - [x] Fails with invalid token
    - [ ] Fails with duplicate machine name  # TODO
"""
```

### Benefits

1. **Single source of truth**: Specs in docs, not scattered in code comments
2. **Test planning**: Writing scenarios first ensures coverage before coding
3. **Discoverability**: Easy to find what a feature should do
4. **Maintenance**: Update spec once, code/tests follow

### Workflow

1. **New feature**: Write spec in `docs/` first
2. **Implementation**: Create code file, add `Spec: docs/...` reference
3. **Testing**: Create test file, list scenarios, mark as `[ ]`
4. **Implement tests**: Write test, mark scenario as `[x]`

## Architecture DDD (Domain-Driven Design)

The sync system follows a DDD architecture. You MUST continue with this approach:

### Structure

```
src/syncagent/client/sync/
├── domain/           # Pure business logic (NO external dependencies)
│   ├── priorities.py # MtimeAwareComparator - event deduplication strategy
│   ├── transfers.py  # Transfer state machine with validated transitions
│   ├── conflicts.py  # ConflictOutcome, RaceConditionError
│   └── decisions.py  # DecisionMatrix for concurrent event handling
├── workers/          # Implementation details (API calls, state updates)
│   └── transfers/    # Actual transfer logic with external dependencies
├── coordinator.py    # Orchestration using domain types
├── queue.py          # Event queue using domain comparators
└── types.py          # Shared types (SyncEvent, SyncEventType, etc.)
```

### Rules

1. **domain/ is pure**: No HTTP clients, no state DB, no file I/O. Only business rules.
2. **workers/ has dependencies**: This is where API calls, state updates, and file operations go.
3. **Use domain types**: When adding new business logic, put it in domain/. Coordinator and queue should use domain types.
4. **Don't over-abstract**: Only create domain abstractions if they're used by multiple consumers. Remove unused code.

### Examples of what goes where

| Logic | Location | Why |
|-------|----------|-----|
| Event comparison rules | domain/priorities.py | Pure logic, no deps |
| Transfer state machine | domain/transfers.py | Pure state transitions |
| Decision matrix | domain/decisions.py | Declarative rules |
| File upload/download | workers/transfers/ | Needs HTTP client |
| Conflict file renaming | workers/transfers/conflict.py | Needs file I/O |
| State DB updates | workers/ or coordinator | Needs LocalSyncState |