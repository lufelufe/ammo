# Ops — System Pack

Operations & automation domain for the AI OS itself.

## Scope
- Schedule recurring work.
- Monitor system/runtime state and report anomalies.
- Run maintenance routines.

## Boundaries
- May read `runtime/` to observe state; writes only to its `memory/` and `runtime/`.
- Uses `cron` and `shell.run` tools when granted.
- Holds no secrets. Credentials are resolved at runtime by model adapters.

## Status
Scaffold (Milestone 1): the contract is declared; behavior is not implemented.
