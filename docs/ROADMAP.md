# AMMO Roadmap

The kernel is built in phases. **Work only on the current milestone**
(constitution rule 1). Do not implement future milestones unless explicitly
asked (rule 2).

> **Two numbering systems — do not confuse them.**
> - **Conceptual phases (0–10, below)** describe the kernel loop stages
>   (structure → … → confidence → memory → real models). These are *design*
>   order.
> - **Delivery milestones** are the order we actually build in, which may
>   interleave infrastructure ahead of a conceptual phase. E.g. the
>   *CLI `doctor` / `list-systems`* self-inspection tooling shipped as a
>   **delivery milestone** and is **not** the same as conceptual **Phase 2
>   (Task Understanding)**, which is still unbuilt. Infrastructure milestones
>   are tracked under "Delivery log" below.

> One-line arc:
> **structure → register → analyze → form team → mock execution → confidence → memory → connect real models**

## Milestones

| Phase | Name                          | Summary                                                        | Status |
|-------|-------------------------------|----------------------------------------------------------------|--------|
| 0     | Constitution & skeleton       | Repo layout, architecture docs, minimal CLI. **No orchestration.** | ✅ done |
| 1     | System pack structure         | Define the System Pack Contract (`.ammo/` meta layer) & registries. | ✅ done |
| 2     | Task Understanding            | Parse intent, constraints, success criteria.                   | 🟡 v0 (delivery M4) |
| 3     | Capability Graph              | Model capabilities and their relationships.                    | 🟡 v0 (delivery M5) |
| 4     | Dynamic Team Formation        | Assemble minimal sufficient teams per task.                    | 🟡 v0 (delivery M6) |
| 5     | Mock Execution                | Dry-run teams without spending real model calls.               | 🟡 v0 (delivery M7) |
| 6     | Confidence Engine             | Quantify trust; decide escalate/accept.                        | 🟡 v0 (delivery M9) |
| 7     | Memory Feedback               | Persist outcomes; reshape future team formation.               | 🟡 v0 (delivery M10) |
| 8     | System connection (universal) | Connect ANY directory as a pack (mount + scoped permissions).   | 🟡 v0 (delivery M12) |
| 9     | Real adapters                 | Authenticated CLIs (claude/codex, multi-model) + paid API HTTP route. | ✅ v1 |
| 10    | Model pool                    | Gorgon Halo / OSS model pool.                                  | planned |

## Milestone 0 — Bootstrap (done)

**Done when:**

- [x] Clean repository layout established.
- [x] `src/ammo/` holds code; `systems/ registry/ memory/ runtime/ vaults/`
      hold data.
- [x] Architecture & philosophy documents written.
- [x] `pyproject.toml` for a Python project.
- [x] Minimal test setup that passes.
- [x] `.gitignore` excludes secrets, runtime logs, caches, virtualenvs,
      credentials.
- [x] No API keys or tokens anywhere.
- [x] `python -m ammo --help` works.

**Explicitly NOT in Milestone 0:** any orchestration logic — task
understanding, capability graphs, team formation, mock execution, confidence,
memory, or model adapters.

## Milestone 1 — System Pack Contract (done)

**Done when:**

- [x] `systems/{personal,research,coding,ops}/` each declare a `.ammo/` meta
      layer (`manifest`, `routing`, `memory_map`, `permissions`, `workflows`)
      and a `system.md`.
- [x] `registry/{systems,models,tools,roles}.yaml` exist.
- [x] `vaults/ResearchVault/` exists.
- [x] The contract is documented in `docs/SYSTEM_PACK_SPEC.md`.
- [x] Validation tests ensure required files exist for each pack; `pytest` passes.
- [x] No execution/orchestration logic; no secrets.

## Delivery log

Delivery milestones (user-driven build order) that ship infrastructure ahead of
the conceptual phases. Conceptual **Phase 2 (Task Understanding) onward remain
unbuilt.**

- **Delivery M2 — CLI self-inspection.** `ammo doctor` (checks root, folders,
  registries, packs, pack `.ammo` files, runtime/memory writability) and
  `ammo list-systems` (reads `registry/systems.yaml`).
  `src/ammo/{paths.py,doctor.py}`.
- **Delivery M3 — Registry & pack loaders.** `src/ammo/registry/` package
  (`loaders.py`, `pack_loader.py`, `errors.py`) loads and *validates* the four
  registries and each `.ammo/` pack, with clear validation errors. New command
  `ammo inspect-system <id>` prints a structured pack summary. Read-only: no
  model execution, no team formation, no touching personal/investment content.
- **Delivery M4 — Task Understanding Engine v0** *(conceptual Phase 2)*.
  `src/ammo/kernel/task_understanding/` turns a request into a `TaskVector`
  (domain, intent, risk, complexity, context_size, tools, candidate_systems,
  output_type, privacy, needs_*, tags) using bilingual rule-based
  classification and pack routing metadata. New command `ammo analyze "<text>"`
  outputs JSON. No model call. Still **not** built: capability graph (P3) and
  team formation (P4).
- **Delivery M5 — Capability Graph v0** *(conceptual Phase 3)*.
  `src/ammo/kernel/capability_graph/` loads model nodes from
  `registry/models.yaml` (7 mock models with roles, capabilities, context,
  cost/latency/warmth) and scores them against a `TaskVector` with explainable
  reasons. New commands `ammo list-models` and `ammo score-models "<text>"`.
  Models are still plugins/mocks — no real call. Still **not** built: team
  formation (P4).
- **Delivery M6 — Dynamic Team Formation v0** *(conceptual Phase 4)*.
  `src/ammo/kernel/team_formation/` turns a `TaskVector` + `CapabilityGraph`
  into an `ExecutionPlan` (selected_system, selected_team of (role, model),
  roles, reasoning_summary, required_tools, risk_controls, expected_outputs).
  Rule-based templates: simple→fast_worker; research→researcher+skeptic+
  synthesizer; investment→researcher+critic+judge; high-risk coding→planner+
  builder+critic+test_runner; ops→triage+operator+rollback_critic. Positions are
  resolved to models by scoring the graph with diversity. New command
  `ammo plan-team "<text>"`. **The plan is not executed** (that is Phase 5).
- **Delivery M7 — Adapter Contract + Mock Workers** *(conceptual Phase 5 +
  adapter interface)*. `src/ammo/adapters/` defines the vendor-neutral contract
  (`BaseModelAdapter`, `AdapterRequest`, `AdapterResponse`, `ToolRequest`,
  `Evidence`) and a deterministic offline `MockAdapter` with role-based workers
  (planner, builder, critic, researcher, skeptic, synthesizer, judge,
  fast_worker). `src/ammo/kernel/mock_execution/` walks an ExecutionPlan through
  adapters (context flows member→member) into a structured `ExecutionResult`.
  New command `ammo run --mock "<text>"`. **AMMO knows only the adapter
  contract** — no real Claude/Codex/OpenAI/local call. `aggregate_confidence` is
  a provisional mean; the real Confidence Engine is Phase 6.
- **Delivery M8 — Execution Graph + Run Logging** *(where AMMO's memory begins)*.
  `src/ammo/kernel/executor/` converts an ExecutionPlan into an ordered
  `ExecutionGraph`, runs it sequentially (`Runner`, adapter-factory injected),
  and `RunStore` persists every run under `runtime/runs/<run_id>/`
  (`input.json`, `task_vector.json`, `execution_plan.json`, `step_outputs.json`,
  `evidence.json`, `final_output.md`, `run_summary.json`). New commands
  `ammo run --mock "<text>"` (prints run_id + path) and `ammo show-run <id>`.
  Supersedes M7's `mock_execution` package. No real model call.
- **Delivery M9 — Confidence Engine v0** *(conceptual Phase 6; AMMO's
  differentiator)*. `src/ammo/kernel/confidence/` computes an **evidence-based**
  confidence score (0–1), band, positive/negative reasons, and a required next
  action from the TaskVector, plan, adapter responses, evidence, objections, and
  risk. It **never reads a model's self-reported confidence**. Rules: tests
  passed / independent critic pass / model agreement raise it; unresolved
  objections / high risk / missing evidence / mock-only lower it. `run` now
  writes `confidence_report.json` and prints a card with `--show-confidence`.
- **Delivery — multi-account Claude + summon accessibility.** Two-plus Claude
  accounts on one Mac work WITHOUT switching macOS users: `CLAUDE_CONFIG_DIR`
  fully separates auth slots (verified live), so the catalog ships a
  `claude-code-b` provider (env `~/.claude-b`) that owns `claude_b_critic`
  when logged in and gracefully falls back to the primary account when not —
  true 2-account teams by just logging in (`CLAUDE_CONFIG_DIR=~/.claude-b
  claude` → /login). Providers carry per-provider env (paths, never secrets)
  through detection and invocation, and auth now requires the expected output
  marker, fixing a live-found false-positive (`claude auth status` exits 0
  even logged out). Summon works from more entry points: a `./ammo` launcher
  at the repo root (no venv activation), the summon line directly in
  `CLAUDE.md`, native `AGENTS.md` for Codex, and `QWEN.md`/`GEMINI.md`
  pointer shims.
- **Delivery — closing sweep (all remaining engineering backlog).** Recurring
  negative confidence reasons are recorded per run and aggregated by system
  evaluation into "recurring issue (n/N runs): ..." suggestions; dream's
  journal insights now name the best model per seat (turns joined with run
  confidences); exploration schedules anneal per SEAT with a convergence
  readout in `ammo efficiency`; the infra test runner became a first-class
  graph node (FIXED_MODELS emptied); a Linux bwrap isolation route is shaped
  (unit-tested, unverified on real Linux); `aggregate_confidence` renamed to
  `self_reported_mean` (informational only); `connect` warns on nested
  sources; runs print a feedback hint so ground truth accumulates.
- **Delivery — workflows.yaml stage routing.** A pack's declared workflows now
  drive team formation: a workflow whose normalized id EXACTLY matches the
  task's intent or a tag routes the team through its stages (stage roles
  resolve as positions; unknown roles are skipped; a workflow with no usable
  stage falls back). Routing order: preferences.default_template -> matching
  workflow -> domain template — exact-match-only, so packs can't hijack
  unrelated tasks. Workflow-routed teams inherit the domain template's tools
  and risk controls (governance is a domain property), and the workflow's own
  confidence_gate now gates acceptance/self-heal (limits.yaml still wins;
  escalation falls back to routing.yaml's on_low_confidence). The eval suite
  mirrors the CLI routing; personal briefing and investment cases now expect
  their declared pipelines.
- **Delivery — Deterministic epsilon exploration (annealed).** The advisor now
  schedules exploration as a FUNCTION of recorded history — no randomness, so
  identical memory yields identical decisions: every ~1/ε-th attempt in a tag
  is an exploration run (ε = 0.2 annealing with experience, half-life 20
  attempts), on which candidates tried fewer times than the incumbent receive
  a nudge deliberately above the advisory cap (qualified-only, so capability
  gating holds). A stuck winner can now be dethroned on schedule and wins its
  seat back by earning it; cold start never explores; plan notes show
  "exploration run (ε=…, attempt N)".
- **Delivery — API/HTTP adapter (the paid route).** `HttpAdapter` reaches
  models through the Anthropic Messages API or OpenAI chat API using stdlib
  urllib (no new deps). Rule 4 is structural: the adapter holds only the env
  var NAME and reads the key inside execute() at call time — nothing secret on
  the object or in artifacts. Engages only under `--allow-paid` and only when
  no no-extra-cost route serves the model; real response usage becomes
  `estimated=False` and is priced as actual spend; API errors surface as
  retryable failure markers. Transport is injectable, so the whole route tests
  offline. Also updates the phase table: Phase 9 (real adapters) is now v1.
- **Delivery — OS-level isolation (macOS seatbelt).** With `sandbox-exec`
  available, `--execute-tools` shell commands run **kernel-confined**: network
  denied, writes only inside the sandbox dir (`/dev` excepted), HOME/TMPDIR
  remapped into the sandbox — verified live (outside `touch` -> "Operation not
  permitted", socket -> PermissionError, `git init/add` works confined). Under
  isolation the tiny allowlist is bypassed (escalation commands stay banned),
  so arbitrary commands including git become runnable; without it the soft
  allowlist remains and `doctor` notices the gap. SBPL rule order (last match
  wins) is asserted in tests.
- **Delivery — Triage: self-diagnosis with proposed fixes.** Any unhandled CLI
  error becomes a diagnosis card (problem / likely cause / concrete fixes)
  instead of a traceback — rules match the exception FAMILY (MRO), so wrapped
  errors like ValidationError(RegistryError) or sqlite3 subclasses hit the
  right remedy (including "restore the dream backup"). After every run,
  failure signals (invocations that kept failing, gate-denied tools, unpriced
  models, all-estimated usage in real mode) print actionable diagnoses naming
  the exact file or command to fix. Unknown errors still get a generic card —
  nothing is swallowed silently.
- **Delivery M19 — Spec wiring: the optimization specs govern the engines.**
  `preferences.yaml` → formation (default_template override; qualified-only
  `model_bias` clamped below a capability match; `preferred_capabilities`
  bonus). `limits.yaml` → formation + acceptance (`max_team_size` truncation in
  template order; `cost_class_max` candidate cap with unfillable-seat fallback;
  `confidence_gate`/`escalation` reported after assessment). `verification.yaml`
  → confidence (declared `success_evidence` present/missing moves the score).
  `context.md` + each role's distilled memory (`insights.md` + `last.md`) are
  injected into every worker request — the role journal loop closes: record →
  dream-distill → read back.
- **Delivery — Primary seat wiring.** The summoning host's model
  (`ammo.config.yaml`) anchors the LEAD seat: +1.5 for a qualified primary —
  breaks genuine ties toward the host, can never outweigh a capability match.
- **Delivery — Sandbox→real promotion (`ammo promote`).** Runs with
  `--execute-tools` record their sandbox; `promote RUN_ID` shows per-file
  unified diffs (dry-run default) and `--apply` copies files after backing up
  pre-images into the run dir. Targets come from the system's `source_path`
  (read-only connections refused) or `--to`; every path re-passes the
  PermissionGate incl. `.ammoignore`. `doctor` now suggests `ammo dream` when
  memory exceeds the consolidation window.
- **Delivery — Tool outcomes feed confidence**. The Confidence Engine now
  scores tool evidence: each denied tool (a member wanted a capability it never
  got) and each failed execution lowers the score (−0.06 each, two scored per
  kind with the rest counted), successful side-effecting execution raises it
  (+0.05), and `required_next_action` points at unresolved tool issues. Closes
  the loop: permission gate → Evidence → confidence → next action.
- **Delivery — `ammo dream` (memory consolidation)** *(automates
  `docs/MEMORY_DREAM.md`'s quantitative pass)*. Dry-run by default, `--apply`
  backs the DB up first. Rebuilds `model_performance`/`team_synergy` from the
  last `--window N` runs (default 50) — which fixes three decay modes at once:
  stale runs no longer dominate all-time averages, legacy domain-keyed rows
  merge into system tags via tag re-derivation, and rows for models absent from
  the registry are dropped as orphans. Per-model cost/token averages carry over
  from a pre-rebuild snapshot (runs don't store per-model usage). Prunes run
  rows + `runtime/runs/` dirs beyond the window and distills oversized role
  journals into `insights.md` + the most-recent N entries. Idempotent.
- **Delivery M18 — Summon protocol & bootstrap** *(the entry ritual)*. The
  summon word is **"ammo"**, identical in every environment (`docs/SUMMON.md`;
  the auto-loaded `AGENTS.md` is the universal agent shim, passing
  `--host <id>`). `ammo start` runs a 4-step propose-don't-interrogate wizard on
  first summon — the summoning host anchors the **primary model** (Claude Code →
  claude, Codex → codex), detected providers propose the model set, permission
  steps (connect/bind) stay explicit, and the default `--optimize` objective is
  persisted to machine-local `ammo.config.yaml` (git-ignored) which
  `run`/`plan-team` now honor. Repeat summons skip setup and print the ready
  summary (`ammo status`); `--reconfigure` redoes it.
- **Delivery — Docs dream pass 1** *(2026-07-02; per `docs/MEMORY_DREAM.md`)*.
  Consolidated documentation memory: `MODEL_ADAPTER_SPEC.md` rewritten to
  implemented reality (contract/adapters/providers, was M0 "not yet
  implemented"); README layout/quick-start/status refreshed (added `evals/`,
  real command surface) and its constitution copy replaced with a pointer to
  the canonical `AMMO_MANIFESTO.md` §5 (the copy had drifted — rule 8 was
  missing); `BACKLOG.md` leaned to open items only (resolved history lives
  here and in git). Earlier review pass 1 had added the DB migration guard
  (`MemoryStore._migrate`).
- **Delivery — Real usage parsing** *(2026-07-02)*. Provider CLIs now run in
  structured-output mode (`claude -p --output-format json`, `codex exec --json`;
  shapes verified live) and `src/ammo/adapters/usage_parsers.py` extracts the
  clean final text plus **real token usage** (`estimated=False`) and, for
  claude, the **provider-reported cost** (`Usage.cost_usd`) — which wins over
  book pricing in `run_economics`. Graceful fallback to the chars/4 estimate on
  any unexpected output. Live-verified end-to-end: a real research run recorded
  69k/1.2k real tokens and $0.26 reported cost per claude member. Honest
  finding: each `claude -p` call carries full-session overhead (~$0.2–0.3
  equivalent) — lighter invocation is queued in the backlog.
- **Delivery — Provider invocation VERIFIED live** *(2026-07-02, claude 2.1.198 /
  codex-cli 0.139.0)*. Real auth checks (`claude auth status`, `codex login
  status`) and stdin invocations (`claude -p`, `codex exec
  --skip-git-repo-check`) confirmed by live calls and baked into
  `DEFAULT_CATALOG` (fixing the `codex exec -` literal-prompt bug). First real
  end-to-end `run --real`: a research team ran 2 live claude calls with proven
  member→member context flow (the skeptic critiqued the researcher's actual
  output). Runner timeout raised to 180s for real calls.
- **Delivery M17 — Efficiency protocol v0** *(quality per resource)*.
  `AdapterResponse.usage` tracks per-call tokens (deterministic estimates until
  CLIs report real counts). `registry/pricing.yaml` + `src/ammo/economics/`
  estimate cost from tokens **regardless of route** — `api` = real spend,
  `subscription` = equivalent value, `local` = 0 — with a `PriceSource` hook for
  a future price-search module and `ammo pricing [set]` for manual updates.
  Every `run` prints and stores an economics block (model count, per-model
  tokens/cost, total) in `run_summary.json` **and** in memory (`runs` +
  `model_performance.average_tokens/average_cost` + `team_synergy.average_cost`,
  with migration back-fill), so cost sits **inside the improvement loop**:
  `plan-team`/`run --optimize performance|cost|speed|balanced` shifts both the
  static weights and the memory advisor (recorded-cost/tokens economy term) —
  the same task yields different optimal combinations per objective. New
  command `ammo efficiency` reports quality-per-$ per model/team per system.
- **Delivery — Sandboxed side-effecting tools v0** *(Phase 9)*.
  `src/ammo/tools/sandbox.py` adds a **soft sandbox** for permitted
  side-effecting tools: a confined per-run working directory (path escape
  raises), a minimal env (no inherited secrets), a tiny **command allowlist**
  (echo/ls/cat/… — non-destructive, no-network), and a timeout. With
  `run --execute-tools`, `fs.write` really writes (mirrored into the sandbox,
  never the real target) and allowlisted `shell.run` really executes — both
  produce real Evidence; dangerous commands (e.g. `rm`) are refused even when
  the tool is permitted. `git`/network remain deferred (need OS-level
  isolation). Opt-in flag, so default runs are unchanged. Sandboxes live under
  `runtime/sandbox/<tmp>/`.
- **Delivery — Tool execution + permission enforcement v0** *(Phase 9)*.
  `src/ammo/tools/` gates every declared tool call (default-deny). `PermissionGate`
  (built from a system's `permissions.yaml` + `.ammoignore`) checks the tool
  allow-list, network, and read/write path scopes; `ToolExecutor` **actually runs
  the safe read-only tools** (`fs.read`, `doc.read`) into Evidence, records
  permitted-but-side-effecting tools as "not executed (awaiting sandbox)", and
  turns denials into failed Evidence. `run` enforces each worker's declared tools
  and stores the Evidence (visible in `evidence.json` / role journals). Demo: a
  builder's out-of-scope `fs.write` is **denied**, `git` is permitted-not-run, an
  in-scope `fs.read` executes. Pending: sandboxed execution of side-effecting
  tools (write/shell/git/network) and feeding tool failures into confidence.
- **Delivery — Real execution v0** *(Phase 9)*. `run --real` calls authenticated
  CLIs for available models instead of mocks. `RealAdapterFactory`
  (`src/ammo/adapters/resolver.py`) resolves each plan model to a `CommandAdapter`
  via detected providers (subscription CLI / local), substituting `{model}`,
  and **falls back to `MockAdapter`** for models with no available command route
  (reported as real-vs-mock). `Runner(mode="real")` marks the run; confidence is
  computed honestly (real responses carry no structured evidence yet, so scores
  stay modest and escalate). AMMO stores no secrets — the CLI carries its own
  auth. Everything is injectable, so the real path is fully tested offline. Still
  pending: actual **tool execution** and **permission enforcement** (workers get
  a text answer; they don't yet touch files), API/HTTP route, and provider-exact
  invocation flags.
- **Delivery — Eval suite v0**. `evals/*.yaml` hold sample tasks (personal,
  research, investment, coding, ops) with expected outcomes. `src/ammo/evalsuite/`
  runs each through the kernel (static, no memory/binding, mock) and scores five
  metrics — `selected_system_correct`, `selected_team_correct`,
  `confidence_reasonable`, `required_tools_detected`, `policy_decision_correct`.
  `ammo eval --mock` prints per-metric pass rates and stores a report under
  `runtime/reports/`. Deterministic, so re-running across changes measures
  whether AMMO is improving — the signal that makes it a *learning* router.
- **Delivery M16 — Role working dirs + per-system memory + exploration**.
  (1) **Role-bound working directories** at `systems/<sys>/roles/<role>/`
  (`src/ammo/roles/`): every run appends each member's output/evidence to the
  role's journal — traces bind to the ROLE, not the model (persist across model
  swaps). New command `ammo role-log <system> <role>`. Contents are gitignored.
  (2) **Per-system performance memory**: `record_run` and the memory-guided
  advisor now key model/team performance by the **selected system** (fallback
  domain), so "best combination for this directory" is learned per-system.
  (3) **Exploration**: `MemoryAdvisor(explore=…)` gives under-tried qualified
  models a deterministic nudge so a stuck winner can be dethroned; `run` /
  `plan-team --explore [x]` enable it (off by default).
- **Delivery M15 — Model-selection wizard + per-system binding**. `ammo bind
  <system>` selects models for a system: if a prior binding or a memory-best
  combination for that system exists it proposes **reuse** (skip 1-2-3);
  otherwise it runs selection over available providers (subscription / API /
  local) with a custom-id fallback, then verifies connectivity. Non-interactive
  via `--models`/`--reuse`; interactive prompts otherwise. The binding is stored
  at `systems/<id>/.ammo/binding.yaml` and **constrains team formation**
  (`TeamFormer(binding=...)` pins bound roles and restricts the model set), so
  the chosen combination is actually used by `run`/`plan-team`. Memory now keeps
  a `team_signature` per run and `best_team_for_system` derives the best
  combination for a directory. No secrets.
- **Delivery M14 — Provider & availability layer + real (command) adapter**
  *(first slice of conceptual Phase 9)*. `src/ammo/providers/` detects how AMMO
  can reach models — subscription CLIs (installed + authenticated), API keys
  (env var **presence only**, never the value), and local runtimes (discovered
  via a list command). `select_models` prefers no-extra-cost routes (a
  subscription covers a model → the paid API is skipped unless `--allow-paid`).
  `src/ammo/adapters/command_adapter.py` reaches a real model by **calling an
  authenticated CLI** — AMMO stores no secrets and the adapter never
  self-reports confidence. New command `ammo providers`. Everything external is
  injectable, so it is fully tested without real CLIs. Next: **M15** interactive
  model-selection wizard + per-system binding; **M16** role-bound working dirs +
  per-system performance memory + exploration.
- **Delivery M13 — Per-system optimization specs + adopt + evaluation**.
  Optional per-system specs (`preferences.yaml`, `verification.yaml`,
  `limits.yaml`, `context.md`, `.ammoignore`) let each system be tuned; absent =
  safe defaults, never required. `ammo adopt <id>` idempotently brings
  `systems/<id>` up to contract **preserving all existing files** (add-missing
  only, never overwrite). `src/ammo/kernel/evaluation/` + `ammo eval-system <id>`
  / `ammo eval-systems` judge each system's health (works / improvements /
  problems) from contract validity, capability coverage, spec completeness, and
  run history. Specs are loaded + evaluated now; deep engine-wiring
  (preferences→formation, verification→confidence, limits→gate, context→exec,
  ignore→enforcement) is the next step. Read-only; nothing overwritten.
- **Delivery M12 — System Connection & Permissions (universal)** *(reframes
  conceptual Phase 8)*. `src/ammo/connect/` makes AMMO universal: point it at any
  directory and it operates there. `ammo new-system <id>` scaffolds an in-tree
  pack; `ammo connect <path> [--id] [--read-only] [--tools]` attaches an EXTERNAL
  directory **by reference** (`manifest.source_path`) with scoped permissions —
  it **interactively asks read-only vs read-write** at connect time (or takes
  `--read-only`/`--writable`; non-interactive requires the flag); `ammo
  disconnect <id>` removes only the in-repo
  descriptor. Nothing is ever moved or copied (rule 9). `doctor` verifies mount
  sources exist and **notices bare folders**, suggesting `connect`/`new-system`.
  `list-systems`/`inspect-system` show mounts. *personal / research /
  investment are no longer special — they are just directories you connect.*
  Note: permission *enforcement* (sandboxed file access) is declarative here;
  actual enforcement lands with real tool execution (Phase 9+).
- **Delivery M11 — Memory-guided Team Formation** *(closes the loop)*.
  `TeamFormer(graph, memory=...)` now consults a `MemoryAdvisor`
  (`src/ammo/memory/advisor.py`): recorded per-model performance and a proven
  team's per-slot preference add a **bounded** bonus that re-ranks *qualified*
  candidates only — "memory advises, the kernel decides." Capability/risk/
  template guardrails always win (bonus ≤2 < capability +3); cold start /
  `--no-memory` fall back to identical static behavior. `ExecutionPlan.notes`
  explains memory-driven picks. Not done (by design): wholesale team recall,
  epsilon-exploration, finer-than-domain tags (backlog).
- **Delivery M10 — Memory Feedback v0** *(conceptual Phase 7; the learning loop
  begins recording)*. `src/ammo/memory/` is a SQLite store at
  `memory/ammo.sqlite` with three tables: `runs` (run_id, timestamp, domain,
  tags, system, models, confidence, outcome, user_feedback placeholder),
  `model_performance` (per model×task-tag: attempts/successes/avg_confidence/
  last_used), and `team_synergy` (per team signature×task-tag). Each mock run
  updates memory. New commands `ammo memory stats` and `ammo memory runs`. v0
  **records only** — it does not yet reshape team formation.

## Design note — Hermes-agent adoption (post-M1)

Between M1 and M2 we reviewed [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(MIT). Full decision: [`HERMES_INTEGRATION.md`](HERMES_INTEGRATION.md). Threaded
into future phases:

- **P4 (Team Formation)** — support MoA (reference→`aggregator`) and
  delegation (leaf/orchestrator) as named team *topologies*.
- **P6 (Confidence)** — make confidence **evidence-grounded** (Hermes
  `verification_evidence` ledger), not a bare score.
- **P7 (Memory Feedback)** — adopt curator-style usage→curation and recall of
  proven team compositions.
- **P9 (Adapters)** — model adapters follow the declarative `ProviderProfile`
  shape (declaration split from mechanism). `registry/models.yaml` currently
  carries capability-graph fields; adapter-mechanism fields land at the adapter
  layer in P9.

Open forks recorded in the decision doc: agentskills.io interop, ACP inbound
protocol, and vendor-vs-reimplement.

## Suggested next milestone

**Phase 2 — Task Understanding:** parse an incoming request into intent,
constraints, and success criteria, and match it against pack `routing.yaml`
(candidate packs + confidence), still without calling any model. Keep the kernel
free of domain logic and vendor SDKs.
