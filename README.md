# AMMO

**AMMO is not a router. AMMO is the adaptive orchestration kernel of a Personal AI OS.**

AMMO (Adaptive Multi-Model Orchestrator) is not a program that calls a model.
It is a learning AI OS kernel that:

1. **Understands** the problem,
2. **Forms** a temporary AI team to solve it,
3. **Computes** the confidence of the result, and
4. **Remembers** failures and successes to change how the next team is formed.

Models are plugins. **AMMO is the IP.**

---

## Philosophy

A router picks a model. A kernel governs a system.

AMMO treats individual models (Claude, Codex, local/OSS models) as
interchangeable, replaceable *capabilities* behind adapter interfaces. The
durable value — the intelligence that compounds over time — lives in AMMO
itself: task understanding, capability graphs, dynamic team formation,
confidence scoring, and a memory that reshapes future decisions.

See [`docs/AMMO_MANIFESTO.md`](docs/AMMO_MANIFESTO.md) for the constitution.

## Repository layout

```
ammo/
├── README.md
├── AGENTS.md                 # Working guide + constitution copy (auto-loaded by agents)
├── pyproject.toml
├── docs/                     # Architecture, philosophy, roadmap, backlog, playbooks
├── src/ammo/                 # Implementation code (the kernel)
│   ├── kernel/               #   task_understanding / capability_graph / team_formation
│   │                         #   executor / confidence / evaluation
│   ├── adapters/             #   model adapter contract + mock/command adapters
│   ├── providers/            #   provider availability (subscription CLI / API / local)
│   ├── economics/            #   token usage + cost estimation
│   ├── memory/               #   run memory + memory-guided advisor
│   ├── binding/ connect/ roles/ tools/ evalsuite/
│   └── cli.py                #   command surface (see `python -m ammo --help`)
├── tests/                    # Test suite
├── evals/                    # Eval-suite cases (per-domain)
├── systems/                  # System packs (domain capabilities)
├── registry/                 # Registries: systems/models/tools/roles/pricing
├── memory/                   # Learning memory (feedback loop)  [contents gitignored]
├── runtime/                  # Runs, reports, sandboxes          [contents gitignored]
└── vaults/                   # Private data vaults               [contents gitignored]
```

`systems/`, `registry/`, `memory/`, `runtime/`, `vaults/` hold user/system
**data**. `src/ammo/` holds **code**. This separation is deliberate and load
bearing: the kernel must never be entangled with the data it governs.

## Quick start

```bash
python -m ammo --help                     # full command surface
python -m ammo doctor                     # check the AMMO root structure
python -m ammo run --mock "fix the bug in this repo and add tests"
python -m ammo run --real "..."           # call authenticated CLIs (claude/codex)
python -m ammo eval --mock                # score AMMO's decisions
```

## Development

```bash
pip install -e ".[dev]"
pytest
```

## Status

The kernel loop (understand → team → execute → confidence → memory → learn) is
implemented end-to-end, including real execution via authenticated CLIs. Current
state and history: [`docs/ROADMAP.md`](docs/ROADMAP.md); deferred items:
[`docs/BACKLOG.md`](docs/BACKLOG.md).

## Constitution (hard rules)

Canonical copy: [`docs/AMMO_MANIFESTO.md`](docs/AMMO_MANIFESTO.md) §5 (working
copy for agents in [`AGENTS.md`](AGENTS.md)). Headline: **models are plugins,
AMMO is the IP** — no secrets in the repo, adapters own all vendor specifics,
small tested modules, never destructively move user data.
