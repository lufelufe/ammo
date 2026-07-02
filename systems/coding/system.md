# Coding — System Pack

Software engineering domain. Implements, reviews, and refactors code.

## Scope
- Implement a specified change.
- Review a change (ideally with a different model than the implementer).
- Refactor without changing behavior.

## Boundaries
- Writes only to its `memory/` and `runtime/` here; per-task project write scopes
  are granted separately in a later milestone.
- Uses `fs.*`, `shell.run`, and `git` tools when granted.
- Holds no secrets. Credentials are resolved at runtime by model adapters.

## Status
Scaffold (Milestone 1): the contract is declared; behavior is not implemented.
