Rules for AI Agents :

* Never forget to make code that follow best pratices, standards and recommended architectures, think SOLID, YAGNI, KISS, DRY, Clean archi, DDD...
* Never forget to commit frequently and follow conventional commit
* You might be working in parrallel with an other agent or human, so take care to only commit your modifications, I will make sure (Julien) that everybody is not conflicting on their work by giving everyone very separate tasks
* To speed up things, only run tests related to what you modified instead of all tests during dev, and before committing you can run all unit tests for example

When you have zero context, start by reading the README.md, docs/* and TODO.md to see where we are on this project, explore code if necessary

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