# AMMO Backlog — deferred risks & decisions

**Policy (user directive):** do **not** fix these during feature milestones.
Accumulate them here, then resolve in a dedicated consolidation pass, **one item
at a time**, when the user calls for it. Each milestone's "Remaining risks" and
"Open forks" land here instead of being fixed inline.

**Guiding principle to preserve:** AMMO is **domain-neutral / universal**. It
must run for any problem or request, not just investment. Investment is one
capability of the `personal` pack; the kernel hard-codes no domain. Reject any
change that couples the kernel to a single domain.

---

## Open strategic forks — DEFERRED until the real-execution ecosystem settles

*(Decision: these only become meaningful once real adapters / ecosystem are
attached; revisit then. Resolved history lives in the ROADMAP delivery log.)*

1. **Skill interop** — adopt the agentskills.io open standard for AMMO
   capabilities/procedures, or define our own? (from `HERMES_INTEGRATION.md`)
2. **Inbound protocol** — adopt ACP (Agent Client Protocol) as the editor-facing
   entry, or defer?
3. **Code reuse** — vendor specific MIT Hermes modules vs clean-room reimplement.
4. **Environment** — standardize the canonical dev/runtime env (currently `.venv`).

## Deferred risks / cleanups (by area)

### Memory consolidation (`ammo dream` shipped — see docs/MEMORY_DREAM.md)
- Quantitative pass (rebuild/dedup/prune/journal-distill) is implemented. Open:
  - **Doc-layer dream is manual** — prose consolidation needs review; not automated.
  - `insights.md` distillation is counts only; recurring corrections / best model
    per role would be richer.
  - Journal distillation archives by count, no semantic merge of archived turns.
  - A `doctor` notice when run count crosses the window (suggest running `dream`).

### Environment / tooling
- Standardize the run environment: system Python 3.14 lacks pytest/PyYAML; we use
  `.venv`. Decide the canonical dev/runtime env.
- `.gitignore`: decide whether to track `.claude/` and how deep to track
  `vaults/` placeholders (currently 1 level).

### Kernel code
- `src/ammo/cli.py` is growing (7+ commands). Consider splitting handlers into a
  `commands/` module (rule 6 hygiene).
- Duplicate cross-reference validation: `tests/test_system_packs.py` invariants
  overlap `SystemPackLoader._validate()`. Possibly unify.

### Task Understanding (Phase 2 v0)
- Rule/keyword heuristic limits: new slang / context / ambiguity (e.g. "브리핑
  스케줄" personal-vs-ops). Domain ties resolved by `DOMAIN_PRIORITY` (tunable).
- `complexity` / `context_size` are rough heuristics (conjunction/length based).

### Eval suite (v0)
- One case per domain; expand coverage (multiple cases, edge cases, negative
  cases) so metrics are statistically meaningful.
- Baseline is static (no memory/binding). To measure *learning*, add a mode that
  runs eval WITH accumulated memory and compares against the static baseline.
- `confidence_reasonable` only checks the band cap (mock never 'high'); with real
  execution, tighten to expected ranges per case.
- No trend tracking yet — store/compare `runtime/reports/` over time (e.g.
  `ammo eval --compare`) to chart improvement.

### Role dirs / per-system memory / exploration (M16)
- Role workspaces persist output but are not yet **read back** into the next
  run's context (cross-run role memory). Feed `RoleWorkspace.journal` into the
  AdapterRequest context so roles accumulate usable expertise.
- Exploration is a static bonus to under-tried models; there's no epsilon
  schedule or convergence tracking. Consider annealing explore over attempts.
- Per-system memory: model_performance/team_synergy now keyed by system; old
  domain-keyed rows (if any) coexist. No migration/backfill.
- Role workspaces live under `systems/<sys>/roles/` (gitignored). For a mounted
  (external) system, traces still land in-repo, not in the mounted dir — revisit
  if role data should live beside the source.

### Model binding / wizard (Phase 9 / M15)
- The interactive selection prompt (`_prompt_models`) is lightly covered; the
  reuse and `--models` paths are the well-tested ones.
- Verification checks provider availability of bound models, not a real
  round-trip call. Real connectivity verify comes with real adapters.

### Efficiency protocol (M17)
- `codex_builder` pricing is a marked placeholder; update via `ammo pricing set`
  or attach the user's price-search module through the `PriceSource` hook.
- Latency is proxied (latency_class + avg tokens); record real wall-clock per
  member for a true speed objective.
- `efficiency` report ranks models/teams; a per-task-category "recommended combo
  card" (best per objective, side by side) would make it directly actionable.
- Local models priced 0 → efficiency=inf; consider a compute-cost estimate.

### Providers & real adapters (Phase 9 / M14 + real exec)
- **Claude Code per-call overhead is large**: each `claude -p` spins a full
  session (~70-90k tokens incl. cache reads → ~$0.2-0.3 equivalent per member
  call). Consider lighter invocation (reduced system surface, `--strict-mcp-config`,
  session reuse/`--resume`) before scaling real teams.
- **Real-mode confidence is optimistic**: real workers return no structured
  Evidence yet, so nothing lowers the score (0.82 "high" on an unverified
  answer). Feed real evidence (tool results, verification) before trusting
  real-mode confidence bands.
- `ollama run {model}` remains unverified (ollama not installed on this machine).
- **Tool execution — still open** (enforcement + soft sandbox are shipped, see
  ROADMAP delivery log):
  - **OS-level isolation** for git / network / arbitrary commands — the soft
    sandbox's allowlist is deliberately tiny; a container/namespace step is
    needed before broadening it.
  - **Sandbox→real promotion**: `fs.write` mirrors into the sandbox; applying a
    sandboxed change to the real target (with diff review) is not implemented.
  - Feed tool denials/failures into the Confidence Engine (recorded as Evidence
    but do not yet change the score).
  - Confirm `.ammoignore` glob semantics against real trees; sandbox dirs under
    `runtime/sandbox/` have no GC/pruning.
- **API/HTTP route deferred**: real exec is command-based (subscription CLI /
  local). Paid API models have no command invoke → they fall back to mock. A
  proper HTTP adapter (still secret-free via env) is a separate piece.
- Model ids in the provider catalog are the mock ids; map them to real model
  names when adapters are finalized.

### Per-system optimization & evaluation (M13)
- Specs are declared/loaded/evaluated but **not yet wired into the engines**:
  - `preferences.yaml` → bias `TeamFormer` (preferred caps/roles, model_bias,
    default_template).
  - `verification.yaml` → `ConfidenceEngine` (which evidence kinds count as
    success; required_outputs).
  - `limits.yaml` → cap team size / cost, override `confidence_gate` &
    escalation.
  - `context.md` → inject into workers at execution (Phase 9).
  - `.ammoignore` → enforce during file access (Phase 9).
- `adopt` refines at **file granularity** (adds missing files, preserves
  existing). Field-level refine (merge missing keys into a partially-filled file)
  is deferred.
- Evaluation reads memory keyed by `selected_system`; recurring confidence
  *reasons* (e.g. "no real tests") aren't aggregated yet — store/aggregate them
  for sharper improvement suggestions.

### System Connection (Phase 8 v0 / M12)
- Permission **enforcement** is not implemented — `permissions.yaml` scopes are
  declarative. Real sandboxing/file-access gating must land when tools execute
  (Phase 9+). Until then a "connected" pack cannot actually touch its source.
- A connected pack's `manifest.source_path` is an **absolute, machine-local**
  path — not portable across machines and not ideal to commit. Consider a
  gitignore convention or a per-machine mounts file if connected packs should
  stay out of version control.
- No content sync/indexing of the mounted directory yet (just a reference).
- `connect` does not warn if the source path is inside the AMMO repo (nested).

### Memory Feedback (Phase 7 — recording M10, guidance M11)
- Loop is closed for team formation (per-model + synergy bonus). Still open:
  - **Exploration**: v0 is pure exploit (deterministic). Add epsilon-exploration
    so a stuck winner can be dethroned and alternatives discovered.
  - **Wholesale team recall** was intentionally NOT done (recall-as-per-slot
    instead). Revisit only if per-slot proves insufficient.
- "success" is proxied by confidence >= 0.5 (mock). Needs real outcome +
  `user_feedback` signal to be meaningful.
- `task_tag` aggregation uses `domain` only, not the full `tags` list. Consider
  per-tag rows for finer model/team performance.
- Advisor weights (MODEL_WEIGHT/SYNERGY_WEIGHT/MIN_ATTEMPTS/BONUS_CAP) are
  hand-tuned; calibrate against real outcomes.
- Schema versioning: a full numbered-migration framework is still deferred
  (column back-fill exists in `MemoryStore._migrate`).

### Confidence Engine (Phase 6 v0)
- Weights are hand-tuned constants; not calibrated against outcomes. Tune once
  real runs + Memory Feedback (Phase 7) provide ground truth.
- Does not yet compare the score against the pack's `workflows.yaml`
  `confidence_gate` to drive escalate/accept; `required_next_action` is
  rule-based. Wire the gate in when team formation consumes it.
- "Model agreement" is proxied by distinct-models + no-objections, not by
  actually comparing outputs. Real agreement needs output comparison.

### Run Logging (Phase 5 / M8)
- `run_id` uses UTC timestamp + random hex (uuid4). Not content-addressed; two
  identical runs get different ids. Fine for a log, revisit if dedup is wanted.
- Runs accumulate under `runtime/runs/` with no rotation/GC. Add pruning later.
- `runtime/**` is gitignored, so run history is local-only (by design).

### Mock Execution / Adapters (Phase 5 v0 + adapter contract)
- `aggregate_confidence` is a naive mean of self-reported values — replace with
  the real evidence-grounded Confidence Engine (Phase 6).
- Execution is a fixed sequential pipeline (member→member). Real execution may
  need parallel fan-out, retries, and per-member tool execution (tools are only
  *declared* now, never run).
- MockAdapter echoes the user's raw input verbatim (may be non-English) inside
  otherwise-English output — that is request data, not a UI label; revisit if a
  strict UI-language check is wanted.

### Team Formation (Phase 4 v0)
- Template selection is coarse (domain-driven; ops always → ops_incident,
  coding high-risk vs standard by risk only). Real routing should also use pack
  `workflows.yaml` stages + `confidence_gate` rather than hard-coded templates.
- Team positions (planner/builder/critic/…) are a second role vocabulary on top
  of registry roles; `local_test_runner` is a synthetic infra id not in the
  graph. Consider unifying position→role mapping and registering infra runners.

### Capability Graph (Phase 3 v0)
- Scoring weights are hand-tuned; ties broken by id. Revisit when the fleet or
  task types grow.
- Capability/role vocab is duplicated between code (`DOMAIN_CAPABILITY`,
  `INTENT_ROLE`) and `registry/models.yaml`. Consider promoting the capability
  vocabulary into a registry to remove drift.
- ProviderProfile mechanism fields (`api_mode`, `auth_type`, `default_aux_model`,
  `cache`) were dropped from `models.yaml` in M5; reintroduce them at the adapter
  layer in Phase 9.

## Scheduled activations (not bugs — future rule triggers)
- **Constitution rule 9** activates at **Phase 8** (connect personal / research /
  investment-system): must safe-copy or ask for the source path — never
  destructively move existing personal/investment folders.
