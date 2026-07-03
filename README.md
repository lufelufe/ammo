# AMMO

**AMMO is not a router. AMMO is the adaptive orchestration kernel of a Personal AI OS.**

AMMO (**A**daptive **M**ulti-**M**odel **O**rchestrator) is not a program that
calls a model. It is a learning kernel that treats every model — Claude, Codex,
local/OSS — as a replaceable plugin, and keeps the durable intelligence for
itself:

1. **Understands** the task,
2. **Forms** a temporary AI team to solve it,
3. **Executes** it (mock or real) through model adapters,
4. **Scores** the confidence of the result, and
5. **Remembers** what worked and what failed — so the *next* team is formed
   differently.

> **Models are plugins. AMMO is the IP.**

---

## Purpose — why AMMO exists

A router maps one request to one endpoint and stops. It cannot learn, cannot
compose, cannot tell you how much to trust its answer.

AMMO inverts that. The value does not live in any single model — models come
and go, prices change, a better one ships every month. The value lives in the
**kernel**: its ability to understand a task, assemble the *minimal sufficient*
team of capabilities for it, judge the confidence of the outcome, and fold that
outcome back into memory so future decisions improve. Any model can be swapped
out without touching this intelligence, because everything vendor-specific is
confined behind a single adapter contract.

The result is a Personal AI OS kernel: it **schedules** capabilities, **isolates**
itself from the data it governs, and **mediates** every model call — the same
way an operating-system kernel schedules, isolates, and mediates applications.

## System overview

```mermaid
flowchart TB
    task([task request])

    subgraph KERNEL["AMMO KERNEL  —  the IP"]
        direction TB
        TU["1 · Task Understanding<br/><i>intent · constraints · success criteria</i>"]
        CG["2 · Capability Graph<br/><i>which models/roles exist & relate</i>"]
        TF["3 · Dynamic Team Formation<br/><i>minimal sufficient team</i>"]
        EX["4 · Execution<br/><i>mock dry-run · or real</i>"]
        CE["5 · Confidence Engine<br/><i>trust score → accept / escalate</i>"]
        MEM["6 · Memory / Feedback<br/><i>persist outcomes</i>"]

        TU --> CG --> TF --> EX --> CE --> MEM
        MEM -. "reshapes future<br/>team formation" .-> TF
    end

    task --> TU

    EX <==>|"the kernel speaks<br/>only this contract"| CONTRACT{{"ADAPTER CONTRACT<br/><i>one stable interface</i>"}}

    subgraph PLUGINS["models are plugins — each adapts itself to the contract"]
        direction LR
        A1["Claude<br/>adapter"]
        A2["Codex<br/>adapter"]
        A3["Local / OSS<br/>adapter"]
    end

    A1 -. "conforms to" .-> CONTRACT
    A2 -. "conforms to" .-> CONTRACT
    A3 -. "conforms to" .-> CONTRACT
```

The adapter boundary is not a pipe the kernel dumps work into — it is a single
stable **contract** the kernel speaks. Each vendor adapter *adapts itself to
that contract* (the arrows point **up, toward the engine**: adapters conform to
the kernel, never the reverse). Nothing above the boundary knows what a "Claude"
or a "Codex" is; adapters translate the one contract to concrete providers
(authenticated subscription CLIs, paid API/HTTP, or a local model pool). That
inversion — models fit the engine, not the engine the models — is what makes
*"models are plugins"* enforceable rather than aspirational.

### The kernel loop, in one line

```
structure → register → analyze → form team → execute → confidence → memory → learn
```

## Install — one-time setup

Clone the repo and create its virtualenv **once**. Every command below is run
from the **repo root** (`cd` into it first).

```bash
git clone https://github.com/lufelufe/ammo.git
cd ammo
python3 -m venv .venv && .venv/bin/pip install -e '.[dev]'   # one-time
```

Two equivalent ways to run it in a terminal:

- **`./ammo …`** — the launcher uses that `.venv` automatically; no activation
  needed. (If you skip the setup, it prints the exact command to run.)
- **`ammo …`** — after `source .venv/bin/activate`, the `ammo` console script is
  on your `PATH`, so you can drop the `./`.

Both are the same program; the examples below use `./ammo`, but plain `ammo`
works once the venv is activated.

## Controls — how to operate AMMO

### Summon — where to run it

AMMO is summoned differently depending on where you are:

| You are in… | Summon with | Runs from |
|---|---|---|
| **A terminal** | `./ammo start` (or `ammo start` with the venv activated) | the **repo root** (the folder you cloned) |
| **Claude Code** | just say **`ammo`** | any dir — `CLAUDE.md` carries the summon line (`--host claude-code`) |
| **Codex** | just say **`ammo`** | reads `AGENTS.md` natively → its *Summon* section |
| **Qwen / Gemini** | just say **`ammo`** | pointer files `QWEN.md` / `GEMINI.md` → `AGENTS.md` |

Inside an agent host, the one word **`ammo`** is enough — the host's
instruction file (`CLAUDE.md` / `AGENTS.md` / …) runs the summon for you. In a
bare terminal, use the `./ammo` launcher from the repo root. The first summon
runs a short setup wizard; every later one prints a one-screen ready summary.

```bash
./ammo start          # summon: first-run wizard, or the ready summary if configured
./ammo status         # one screen: host, models, systems, memory
```

### Assign roles — who plays each seat

You author a small, human-facing role assignment (**orchestrator / critic /
simple worker / builder**); AMMO detects the usable models, proposes a default
per seat, and lets the summoning host ask you seat by seat. The assignment is
*authority* — the model you pick wins that seat in team formation, and the
internal kernel roles (router/analyst/synthesizer/critic/reviewer/…) are derived
automatically and shown as information.

```bash
./ammo roles plan     # the interview: usable models, candidates, proposed defaults
./ammo roles set --orchestrator claude_b --critic claude_a \
                 --worker codex_builder --builder codex_builder
./ammo roles         # show the current assignment + auto internal-role map
```

In Claude Code, just say **`ammo`** and the host asks you seat by seat as cards;
in a terminal, `./ammo roles set` (no flags) runs the same interview as prompts.

### Interactive shell (recommended)

`ammo enter` opens a stay-inside session: type a request and it runs, or type a
subcommand. Configure once with `set`, and every later request inherits it.

```bash
./ammo enter
> set real                 # mock (default) or real execution
> set optimize speed       # balanced | performance | cost | speed
> set read ./src           # grant read access to a path
> fix the failing test in utils and add a regression test
> status
> feedback <run-id> good   # judge a run — this is the learning signal
> exit
```

### One-shot commands

Run a full request through the kernel loop:

```bash
./ammo run --mock "fix the bug in this repo and add tests"   # dry-run, spends nothing
./ammo run --real "..."                                       # calls authenticated CLIs
./ammo show-run <run-id>                                      # inspect a stored run
./ammo feedback <run-id> good|bad                             # ground truth for learning
```

### The command surface, by stage

| Stage | Commands |
|---|---|
| **Understand** | `analyze` — request → TaskVector (rule-based, no model call) |
| **Capability graph** | `list-models`, `score-models` — score models against a request |
| **Team** | `plan-team` — form a team (ExecutionPlan) without executing |
| **Execute** | `run`, `show-run`, `promote` (apply a run's sandboxed writes after a diff) |
| **Confidence** | surfaced in every `run`; `calibrate` compares scores vs. feedback |
| **Memory / learn** | `memory`, `feedback`, `dream` (consolidate memory), `efficiency` (quality-per-cost) |
| **Systems** | `list-systems`, `inspect-system`, `new-system`, `connect`, `disconnect`, `adopt`, `eval-system(s)` |
| **Providers / models** | `providers` (detect CLIs/API/local), `bind`, `pricing` |
| **Health** | `doctor`, `eval` (score AMMO's decisions), `role-log` |

Full help: `./ammo --help` (or `./ammo <command> --help`).

## Repository layout

```
ammo/
├── README.md
├── AGENTS.md                 # Working guide + constitution copy (auto-loaded by agents)
├── ammo                      # Terminal launcher (no venv activation needed)
├── ammo.config.yaml          # Machine-local summon config (host, models, objective) — no secrets
├── pyproject.toml
├── docs/                     # Architecture, manifesto, roadmap, backlog, playbooks
├── src/ammo/                 # Implementation code (the kernel)
│   ├── kernel/               #   task_understanding / capability_graph / team_formation
│   │                         #   executor / confidence / evaluation
│   ├── adapters/             #   model adapter contract + mock/command/http adapters
│   ├── providers/            #   provider availability (subscription CLI / API / local)
│   ├── economics/            #   token usage + cost estimation
│   ├── memory/               #   run memory + memory-guided advisor
│   ├── dream/                #   memory consolidation
│   ├── binding/ connect/ evalsuite/ commands/
│   └── cli.py                #   command surface (see `./ammo --help`)
├── tests/                    # Test suite
├── evals/                    # Eval-suite cases (per-domain)
├── systems/                  # System packs (domain capabilities)
├── registry/                 # Registries: systems / models / tools / roles / pricing
├── memory/                   # Learning memory (feedback loop)  [contents gitignored]
├── runtime/                  # Runs, reports, sandboxes          [contents gitignored]
└── vaults/                   # Private data vaults               [contents gitignored]
```

`src/ammo/` holds **code**; `systems/ registry/ memory/ runtime/ vaults/` hold
**data**. This separation is deliberate and load-bearing: the kernel must never
be entangled with the data it governs.

## Development

After the one-time [install](#install--one-time-setup), from the repo root:

```bash
source .venv/bin/activate       # or just prefix commands with .venv/bin/
python -m ammo doctor           # check the AMMO root structure
python -m ammo run --mock "fix the bug in this repo and add tests"
pytest
```

## Status

The kernel loop — understand → team → execute → confidence → memory → learn —
is implemented end-to-end, including **real** execution via authenticated CLIs
(multi-model), measured consensus (N-way lead sampling), grounded workers (read
real files before answering), measured latency, and an interactive shell.
Current state and history: [`docs/ROADMAP.md`](docs/ROADMAP.md); deferred items:
[`docs/BACKLOG.md`](docs/BACKLOG.md).

## Constitution (hard rules)

Canonical copy: [`docs/AMMO_MANIFESTO.md`](docs/AMMO_MANIFESTO.md) §5 (working
copy for agents in [`AGENTS.md`](AGENTS.md)). Headline: **models are plugins,
AMMO is the IP** — no secrets in the repo, adapters own all vendor specifics,
small tested modules, never destructively move user data.

## Further reading

- [`docs/AMMO_MANIFESTO.md`](docs/AMMO_MANIFESTO.md) — the constitution & philosophy
- [`docs/AMMO_ARCHITECTURE.md`](docs/AMMO_ARCHITECTURE.md) — architecture in depth
- [`docs/MODEL_ADAPTER_SPEC.md`](docs/MODEL_ADAPTER_SPEC.md) — the adapter contract
- [`docs/SYSTEM_PACK_SPEC.md`](docs/SYSTEM_PACK_SPEC.md) — how system packs extend the kernel
- [`docs/SUMMON.md`](docs/SUMMON.md) — the summon protocol
- [`docs/ROADMAP.md`](docs/ROADMAP.md) · [`docs/BACKLOG.md`](docs/BACKLOG.md)
```
