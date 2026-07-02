# AGENTS.md — working guide for anyone (human or agent) building AMMO

This file is **tool-neutral on purpose**: AMMO is model-neutral (models are
plugins behind adapters), so its development guide is not tied to any single
assistant. Claude Code, other agents, and humans should all follow this.

> **AMMO is not a router. AMMO is the adaptive orchestration kernel of a Personal AI OS.**
> It understands a problem, forms a temporary AI team, computes the confidence of
> the result, and remembers successes/failures to change how the next team is
> formed. See `docs/AMMO_MANIFESTO.md` and `docs/AMMO_ARCHITECTURE.md`.

## Constitution (hard rules — canonical copy in `docs/AMMO_MANIFESTO.md` §5)

1. Work only on the current milestone.
2. Do not implement future milestones unless explicitly asked.
3. Preserve the architecture: **models are plugins, AMMO is the IP.**
4. Do not store API keys, OAuth tokens, secrets, or credentials.
5. Keep Claude/Codex/local models behind adapter interfaces.
6. Prefer small, testable modules over large monolithic code.
7. Add or update tests for every functional change.
8. At the end of a milestone, report: changed files, commands run, test results,
   remaining risks, suggested next milestone.
9. Do not destructively move existing personal/investment folders. If importing
   is needed, create a safe copy or ask for the source path.

## Summon ("ammo")

When the user says **"ammo"** (bare, as a wake word), run
`python -m ammo start --host <your-host-id>` (`claude-code`, `codex`, …) and
show its output. First summon = a 4-step setup wizard; later summons = the
ready summary. Do not auto-connect workspaces or bind models on the user's
behalf — those grant permissions and stay explicit (`ammo connect`,
`ammo bind`). Protocol: `docs/SUMMON.md`.

## Kernel loop → where each stage lives

```
understand → capability graph → form team → (mock) execute → confidence → memory ↺
```

| Stage | Module | CLI |
|-------|--------|-----|
| Summon / bootstrap | `src/ammo/bootstrap.py`, `src/ammo/config.py` | `start`, `status` |
| Memory consolidation | `src/ammo/dream/` | `dream [--apply]` |
| Self-diagnosis (triage) | `src/ammo/triage.py` | automatic: unhandled errors + run failure signals become diagnosis cards |
| Task understanding | `src/ammo/kernel/task_understanding/` | `analyze` |
| Capability graph | `src/ammo/kernel/capability_graph/` | `list-models`, `score-models` |
| Team formation | `src/ammo/kernel/team_formation/` | `plan-team` |
| Execution (mock) | `src/ammo/kernel/executor/` + `src/ammo/adapters/` | `run --mock`, `show-run` |
| Confidence | `src/ammo/kernel/confidence/` | `run --show-confidence` |
| Memory + guided formation | `src/ammo/memory/` (`advisor.py`) | `memory stats|runs` |
| System eval / eval suite | `src/ammo/kernel/evaluation/`, `src/ammo/evalsuite/` | `eval-system(s)`, `eval --mock` |
| Providers / availability | `src/ammo/providers/` | `providers` |
| Per-system binding | `src/ammo/binding/` | `bind` |
| Role workspaces | `src/ammo/roles/` | `role-log` |
| Connect / adopt | `src/ammo/connect/` | `connect`, `new-system`, `adopt`, `disconnect` |

**Current state (important):** `run --mock` executes on **`MockAdapter`**
(deterministic, offline). `run --real` calls **authenticated CLIs** for available
models (`RealAdapterFactory`), falling back to mock otherwise. Tool calls are
**permission-enforced** (`src/ammo/tools/`, default-deny against
`permissions.yaml` + `.ammoignore`); safe read-only tools execute for real. With
`run --execute-tools`, permitted side-effecting tools run in a **soft sandbox**
(confined dir, minimal env, timeout): on macOS the shell runs **kernel-confined
via seatbelt** (network denied, writes only inside the sandbox — git works),
falling back to a tiny allowlist elsewhere; `ammo promote RUN_ID` applies
sandboxed writes to the real target after a diff review. Per-system specs
(preferences/limits/verification/context.md) govern the engines, and errors
self-diagnose via triage. Still pending: Linux isolation and the API/HTTP
route (see `docs/BACKLOG.md`).

## How to add things (smallest footprint first)

- **A new CLI command:** add a subparser in `build_parser()` and a thin
  `_cmd_x` handler in `src/ammo/cli.py`; put real logic in a module, not the
  handler.
- **A new kernel subsystem:** `src/ammo/kernel/<name>/` with small modules and an
  `__init__.py` that exports the public API; add a `tests/test_<name>.py`.
- **A new model adapter:** implement `BaseModelAdapter` (`src/ammo/adapters/
  contract.py`). It must not self-report a confidence the engine trusts, and it
  must not leak vendor SDKs above the adapter boundary.
- **A new per-system spec:** extend `pack_contract` + the loader + `connect/
  templates.py`; keep it **optional** with safe defaults (never break existing packs).

## Working conventions

- **Language:** all product UI (CLI banners, help, output, JSON, errors) is
  **English**. Code/docs/comments/commits are English. Keyword lexicons and test
  fixtures may hold other languages (they are data, not UI). Chat replies follow
  the user's input language.
- **Milestones:** one at a time; end with the rule-8 report.
- **Deferred risks:** do NOT fix "remaining risks" mid-milestone — append them to
  `docs/BACKLOG.md` and resolve later, one at a time, in a review pass. Raise
  genuine multi-way forks as questions, not silent defaults.
- **No secrets, ever.** Providers detect *presence* (env var NAME, CLI login),
  never values; adapters call authenticated CLIs. AMMO holds no keys.
- **Commits are logical units.** One reviewable, revertable concern per commit
  (a milestone usually = one commit; docs-consolidation and risk fixes are their
  own commits). Never push without an explicit user instruction.

## Boundaries (what must NOT depend on what)

- The **kernel imports no vendor SDK.** All model access goes through
  `BaseModelAdapter`; `providers/` only detects availability, never reads secrets.
- **Code vs data are separate:** code in `src/ammo/`; data in `systems/`,
  `registry/`, `memory/`, `runtime/`, `vaults/`. The kernel hard-codes **no
  domain** (domain-neutral — investment is just one pack capability).
- Confidence is **evidence-based**, computed by `ConfidenceEngine` — never taken
  from a model's self-report.

## Memory hygiene (full playbook: `docs/MEMORY_DREAM.md`)

- **Absolute dates only** in anything persisted (docs, memories, records).
- **One definition place per rule.** The constitution's canonical copy is
  `docs/AMMO_MANIFESTO.md` §5; lower layers don't restate higher-layer rules —
  delete duplicates silently (at most one pointer sentence).
- **No stale references.** A doc or memory row pointing at a file/symbol/model
  that no longer exists is a bug: verify or delete it when touched.
- **Keep indexes lean.** `docs/BACKLOG.md` holds open items only (resolved
  history lives in git and the ROADMAP delivery log). Memory aggregates should
  not let ancient runs dominate forever.
- **Consolidation is non-destructive**: dry-run/report first, apply behind an
  explicit flag with a backup, logical-unit commits, review before adopting.
- Dream triggers: after registry/model changes, after ~20–30 recorded runs, or
  on request.

## Test discipline

- Run in a local `.venv`: `pip install -e ".[dev]"`, then `pytest`. (System
  Python may lack pytest/PyYAML; `.venv` is canonical for now.)
- **Tests use temporary AMMO roots** — never write runs/memory/role-dirs into the
  real repo tree. A test that runs `run`/`bind`/`adopt` (which write into
  `systems/`) must **`shutil.copytree` the systems tree, not symlink it** — a
  symlinked `systems/` leaks role dirs and bindings into the real repo.
- **Assert invariants, not snapshots.** No change-detector tests (don't freeze
  model lists, counts, or config numbers that legitimately change).
- **UI has three test layers:** (1) capsys output assertions (content),
  (2) **real-TTY interactive tests** via pexpect (`tests/test_ui_tty.py` —
  prompts appear, answers steer, outcomes match), (3) a `--help` surface net
  asserting every registered command is listed. Host-shim UX (saying "ammo"
  inside Claude Code/Codex) stays a manual smoke: summon once after changing
  the Summon section here or `docs/SUMMON.md`.
- After a change, verify the repo stays clean: no `runtime/runs`,
  `memory/ammo.sqlite`, `systems/*/roles/`, or stray packs left behind.

## Doc index

- `docs/AMMO_MANIFESTO.md` — philosophy + constitution (canonical).
- `docs/AMMO_ARCHITECTURE.md` — kernel/data separation, adapter boundary.
- `docs/SYSTEM_PACK_SPEC.md` — the `.ammo/` system-pack contract.
- `docs/MODEL_ADAPTER_SPEC.md` — the adapter contract.
- `docs/HERMES_INTEGRATION.md` — what AMMO adopts/rejects from hermes-agent.
- `docs/SUMMON.md` — the "ammo" summon protocol (boot sequence, per-host shims).
- `docs/MEMORY_DREAM.md` — memory-consolidation playbook (layers, 4 steps); automated by `ammo dream`.
- `docs/ROADMAP.md` — phases + delivery log (status). `docs/BACKLOG.md` — deferred risks/decisions.
