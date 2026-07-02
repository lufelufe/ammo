# Hermes-Agent Adoption Review

**Status:** design decision, taken between Milestone 1 and Milestone 2.
**Subject:** [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
(MIT), a working copy is vendored at `ref/hermes-agent-main/` for study only.

> AMMO reminder: *AMMO is not a program that calls a model. It is a learning AI
> OS kernel that understands a problem, forms a temporary AI team, computes the
> confidence of a result, and remembers successes and failures to change how the
> next team is formed.* This review judges Hermes against that definition.

## 1. Verdict

**Adopt Hermes's edge interfaces and its learning-loop concepts; do not adopt
its core agent shape.** Hermes optimizes for a single long-lived, prompt-cached
conversation ("the core is a narrow waist; per-conversation prompt caching is
sacred"). AMMO optimizes for the opposite: a *fresh temporary team per task*.
So the reusable value is at Hermes's **edges** (adapters, tool registry, plugin
taxonomy, skills, learning loop), not its **center** (the single-agent turn
loop). Crucially, the three things Hermes deliberately lacks —
**confidence scoring, a persistent role-typed team abstraction, and a unified
per-domain system pack** — are exactly AMMO's IP. Hermes validates our
Milestone 1 design by contrast.

License is MIT, so we *may* vendor specific modules (e.g. a provider adapter) or
clean-room reimplement. Default: **reimplement the interface, borrow the shape.**

## 2. Concept mapping (Hermes → AMMO)

| Hermes concept | Where in Hermes | AMMO stage | Decision |
|----------------|-----------------|------------|----------|
| **ProviderProfile** — declarative model adapter (auth/endpoints/quirks), declaration split from mechanism | `providers/base.py`, `plugins/model-providers/*` | Model Adapter / `registry/models.yaml` (P9) | **ADOPT pattern** |
| **Tool registry** — `registry.register(name, schema, handler, check_fn=…)`, availability-gated, AST auto-discovery | `tools/registry.py`, `model_tools.py` | Tools registry + pack `permissions` (P3+) | **ADOPT pattern** |
| **Plugin `kind` taxonomy** — `plugin.yaml { kind: model-provider \| memory \| … }`, per-kind discovery, last-writer-wins override | `plugins/*/plugin.yaml` | Registries (`systems/models/tools/roles`) | **ADOPT idea** |
| **MoA** — reference models fan out → aggregator model decides | `agent/moa_loop.py`, `hermes_cli/moa_config.py` | Dynamic Team Formation (P4) | **ADOPT as a team *topology*** |
| **Delegation / Kanban** — `delegate_task` spawns leaf/orchestrator subagents; kanban board for multi-worker | `tools/delegate_tool.py`, `plugins/kanban/` | Dynamic Team Formation (P4) | **ADOPT as team topologies** |
| **Skills** — `SKILL.md` + frontmatter, agentskills.io open standard, agent-authored | `skills/`, `agent/skill_*.py` | Pack capabilities / procedures (P1/P8) | **CONSIDER open-standard interop** (see §5) |
| **Curator** — usage telemetry → auto pin/archive/patch of agent-created skills | `agent/curator.py`, `tools/skill_usage.py` | Memory Feedback (P7) | **ADOPT concept** |
| **Verification evidence** — passive ledger of what was actually proven (tests/builds run); "never decides" | `agent/verification_evidence.py`, `verification_stop.py` | Confidence Engine (P6) | **ADOPT: confidence must be evidence-grounded** |
| **Curated memory** — `MEMORY.md`/`USER.md` prefetched pre-turn, synced post-turn | `agent/memory_manager.py` | Memory Feedback (P7) | **ADOPT concept** (we already do this for our own memory) |
| **Profiles** — isolated `HERMES_HOME` per instance | `hermes_cli/main.py` | System pack isolation | **ALREADY aligned** (our `systems/<id>` + `memory/<id>`) |
| **Unified entry** — CLI/gateway/ACP/cron all build the *same* agent, differ only in toolset/delivery | `gateway/`, `acp_adapter/`, `cron/` | Entry surfaces (future) | **DEFER**; note ACP as an inbound protocol option (§5) |
| **Confidence scoring** | *not present* in Hermes | Confidence Engine (P6) | **AMMO FILLS THE GAP** |
| **Persistent role-typed team** | *not present* (per-turn presets only) | Dynamic Team Formation (P4) | **AMMO FILLS THE GAP** |
| **Unified system pack (knowledge+permissions+routing)** | *not present* (fragmented) | System Pack Contract (M1) | **AMMO ALREADY UNIFIES** |

## 3. The core philosophical tension (and how AMMO resolves it)

Hermes: **one cached conversation, capability at the edges, never rebuild
context mid-conversation.** AMMO: **rebuild the team per task.** Team
re-formation is precisely the cache-invalidating move Hermes forbids for cost.

Resolution for AMMO:

1. **Push caching-awareness down to the adapter layer**, not the kernel. An
   adapter may keep a warm, cached session; the kernel decides team shape above
   it. (Reflected as a declarative hint in `registry/models.yaml`.)
2. **Re-form the team only when it pays.** Team re-formation is gated by novelty
   / low confidence (Confidence Engine, P6) — not done blindly every task. This
   turns Hermes's cost objection into an AMMO scheduling policy.
3. **Reuse teams via memory.** The Memory Feedback loop (P7) should let a proven
   team composition be *recalled* cheaply for a similar task instead of
   re-derived — the AMMO analogue of a warm cache.

## 4. What we change *now* (declarative only — no execution logic)

These land in the Milestone 1 contract because they are contract shape, not
orchestration:

- **`registry/models.yaml`** gains ProviderProfile-style declarative fields
  (`api_mode`, `auth_type`, `default_aux_model`, `cache`) — still no secrets,
  still adapters-as-plugins.
- **`registry/roles.yaml`** gains an **`aggregator`** role so a MoA-style team
  topology is expressible.
- **Cross-reference invariant tests** (Hermes-style "assert relationships, not
  snapshots"): every role/tool a pack references must exist in the registries.
- **`docs/MODEL_ADAPTER_SPEC.md`** and **`docs/ROADMAP.md`** record the adopted
  patterns per phase.

We do **not** implement MoA, delegation, curator, evidence ledgers, or adapters
here — those are Phases 4/6/7/9.

## 5. Open strategic forks (need a decision before they bind)

1. **Skill interop:** adopt the **agentskills.io** open standard for AMMO
   capabilities/procedures (interop with the Hermes/OpenClaw skill ecosystem),
   or define AMMO's own format? Recommendation: **align with agentskills.io** at
   the procedure layer to inherit an ecosystem; keep `.ammo/` as our own
   governance layer on top.
2. **Inbound protocol:** adopt **ACP (Agent Client Protocol)** as AMMO's
   editor-facing entry (Zed/VS Code/JetBrains), matching Hermes's
   `acp_registry/agent.json`? Recommendation: **defer**, but reserve it as the
   inbound-surface standard rather than inventing one.
3. **Code reuse vs clean-room:** vendor specific MIT modules (e.g. adapt
   `providers/base.py`) or reimplement? Recommendation: **reimplement
   interfaces, borrow shapes**; vendor only if a module is large, stable, and
   generic.

## 6. Out of scope

No Hermes code is imported into `src/`. `ref/hermes-agent-main/` is reference
material only and is git-ignored from the build. Any future vendoring must
preserve MIT attribution and go through an explicit milestone.
