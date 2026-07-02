# AMMO Architecture

This document describes the intended architecture of the AMMO kernel. It is a
**map, not a promise**: only the current milestone is implemented (see
[`ROADMAP.md`](ROADMAP.md)). Everything else is design intent that later
milestones must not violate.

## 1. Design principles

- **Kernel/data separation.** Code lives under `src/ammo/`. User and system
  data live under `systems/`, `registry/`, `memory/`, `runtime/`, `vaults/`.
  The kernel never hard-codes the data it governs.
- **Models are plugins.** Every model is reached through a
  [Model Adapter](MODEL_ADAPTER_SPEC.md). The kernel depends on the adapter
  interface, never on a vendor SDK directly.
- **Small, testable modules.** No monoliths. Each subsystem is independently
  testable.
- **Secret-free repository.** No keys, tokens, or credentials are ever stored.

## 2. Top-level layout

| Path         | Kind | Purpose                                                        |
|--------------|------|----------------------------------------------------------------|
| `src/ammo/`  | code | The kernel implementation.                                     |
| `docs/`      | code | Architecture & philosophy (this constitution).                 |
| `tests/`     | code | Test suite.                                                    |
| `systems/`   | data | System packs — domain capabilities layered on the kernel.      |
| `registry/`  | data | Model & capability registries (what is available to AMMO).     |
| `memory/`    | data | Learning memory; the feedback loop's persistent store.         |
| `runtime/`   | data | Ephemeral run state, logs, mock-execution traces.              |
| `vaults/`    | data | Private, sensitive data vaults (contents never committed).     |

## 3. The kernel loop (target architecture)

Each stage below maps to a future milestone. Milestone 0 implements **none** of
the orchestration logic — it only lays down the substrate and a CLI placeholder.

```
        ┌─────────────────────────────────────────────────────────┐
        │                        AMMO KERNEL                        │
        │                                                           │
  task ─▶  Task Understanding ──▶ Capability Graph                  │
        │          │                     │                          │
        │          ▼                     ▼                          │
        │   Dynamic Team Formation ◀─────┘                          │
        │          │                                                │
        │          ▼                                                │
        │   Mock Execution ──▶ Confidence Engine                    │
        │                              │                            │
        │                              ▼                            │
        │                      Memory / Feedback ──┐                │
        │                              ▲           │ reshapes future │
        │                              └───────────┘ team formation  │
        └───────────────────────────────┬─────────────────────────┘
                                         │  (adapter boundary)
                       ┌─────────────────┼─────────────────┐
                       ▼                 ▼                 ▼
                  Claude adapter    Codex adapter   Local/OSS adapter
```

### Stage responsibilities

1. **Task Understanding** — parse intent, constraints, and success criteria.
2. **Capability Graph** — model of which capabilities exist and how they relate.
3. **Dynamic Team Formation** — select a minimal, sufficient set of capabilities
   / models for the task.
4. **Mock Execution** — dry-run the team without spending real model calls.
5. **Confidence Engine** — quantify trust in a result; decide escalate/accept.
6. **Memory / Feedback** — persist outcomes and adjust future formation.
7. **Adapters** — the only place vendor specifics live.

## 4. The adapter boundary

Nothing above the adapter boundary knows what a "Claude" or a "Codex" is. The
kernel speaks a single, stable adapter contract; adapters translate to concrete
providers. This is what makes "models are plugins" enforceable rather than
aspirational. See [`MODEL_ADAPTER_SPEC.md`](MODEL_ADAPTER_SPEC.md).

## 5. System packs

Domain capabilities (personal, research, investment-system, …) are packaged as
**system packs** under `systems/`. They extend the kernel without modifying it.
See [`SYSTEM_PACK_SPEC.md`](SYSTEM_PACK_SPEC.md).

## 6. Current state (Milestone 0)

- Repository layout established.
- Architecture/philosophy documents written.
- Minimal CLI placeholder (`python -m ammo --help`).
- **No orchestration logic.** Task understanding, capability graphs, team
  formation, mock execution, confidence, memory, and adapters are all future
  milestones.
