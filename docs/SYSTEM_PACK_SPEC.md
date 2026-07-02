# System Pack Specification

A **system pack** is a self-contained unit of domain capability that layers on
top of the AMMO kernel *without modifying it*. Packs are how sub-systems like
`personal`, `research`, `coding`, and `ops` attach beneath AMMO.

This document defines the **System Pack Contract**: the `.ammo/` meta layer the
kernel understands. As of Milestone 1 the contract is **declarative** — the
files describe *what* a pack is and *how* it should be run, but no execution or
orchestration logic exists yet.

> Reminder: *AMMO is not a program that calls a model. It is a learning AI OS
> kernel that understands a problem, forms a temporary AI team, computes the
> confidence of the result, and remembers successes and failures to change how
> the next team is formed.* Each `.ammo` file below maps to a stage of that loop.

## 1. Layout

```
systems/
└── <id>/
    ├── system.md            # human-readable description of the pack
    └── .ammo/               # machine-readable meta layer the kernel reads
        ├── manifest.yaml    # identity & declared capabilities
        ├── routing.yaml     # task understanding / routing
        ├── memory_map.yaml  # the learning-memory feedback loop
        ├── permissions.yaml # the security boundary
        └── workflows.yaml   # team shape + confidence gates (declarative)
```

The five `.ammo` files and `system.md` are **required** for every pack. The
required set is fixed in code at `src/ammo/pack_contract.py` (the single source
of truth used by tests).

Every `.ammo` file starts with:

```yaml
apiVersion: ammo/v1
kind: <Kind>
```

so the kernel can version and dispatch on the contract.

## 2. `manifest.yaml` — identity

Declares that the pack exists and what it offers. This is the first thing the
kernel reads.

| Field          | Meaning                                                       |
|----------------|---------------------------------------------------------------|
| `id`           | Stable pack id; **must equal the folder name**.               |
| `name`         | Human-facing name.                                            |
| `version`      | Pack version.                                                 |
| `status`       | `scaffold` (declared) → later `active`.                       |
| `entrypoint`   | Human doc to read first (`system.md`).                        |
| `description`  | One-paragraph purpose.                                        |
| `tags`         | Free-form classification hints.                               |
| `capabilities` | List of `{id, summary}` the pack can perform.                 |

## 3. `routing.yaml` — task understanding / routing

Tells the kernel's Task Understanding stage *when this pack is relevant* and
which roles it should start from.

| Field                        | Meaning                                          |
|------------------------------|--------------------------------------------------|
| `priority`                   | 0–100; higher wins when multiple packs match.    |
| `match.intents`              | Canonical intent ids this pack claims.           |
| `match.keywords`             | Keyword hints (any language).                    |
| `match.examples`             | Example utterances that should route here.       |
| `default_roles`              | Roles the initial team starts with.              |
| `escalation.on_low_confidence` | What to change when confidence is low (e.g. `add_role:critic`). |

Routing is **advisory input** to the kernel — the kernel makes the final call.

## 4. `memory_map.yaml` — the feedback loop

Declares where the pack's learning memory lives and which signals feed back into
future team formation (Phase 7). No store is created in Milestone 1.

| Field             | Meaning                                                    |
|-------------------|------------------------------------------------------------|
| `namespace`       | Memory namespace for the pack.                             |
| `stores.episodic` | Per-run history: tasks, teams used, outcomes.              |
| `stores.semantic` | Distilled, durable knowledge.                              |
| `vault_bindings`  | Vaults this pack mounts (e.g. `ResearchVault`).            |
| `feedback.writes` | Signals recorded after a run (outcome, confidence, team…). |
| `retention`       | How long each store is kept.                               |

`feedback.writes` is the crux of the philosophy: these are the signals that let
**the next team be formed differently** from the last.

## 5. `permissions.yaml` — the security boundary

The allow-list of what a pack may touch. Deny-by-default is the intent.

| Field         | Meaning                                                        |
|---------------|----------------------------------------------------------------|
| `filesystem.read` / `.write` | Path scopes the pack may read / write.          |
| `vaults.read` / `.write`     | Vaults the pack may access.                     |
| `network.allow`              | Whether any network is permitted at all.        |
| `tools.allow`                | Tool ids (from `registry/tools.yaml`) it may use. |
| `models.allow`               | Adapter ids it may use; `"*"` = any registered. |
| `roles.allow`                | Roles (from `registry/roles.yaml`) it may staff. |

**No secrets** live here. Model adapters resolve credentials at runtime from the
environment or a secret manager (constitution rule 4).

## 6. `workflows.yaml` — team shape + confidence gates

Named, declarative task templates. Each workflow describes the **shape of the
temporary team** (ordered `stages`, each a `role` doing a step) and a
`confidence_gate`. Execution is **not** implemented in Milestone 1.

| Field                  | Meaning                                               |
|------------------------|-------------------------------------------------------|
| `workflows[].id`       | Workflow id.                                          |
| `workflows[].stages`   | Ordered `{role, does}` steps = the team composition.  |
| `confidence_gate`      | Minimum confidence to accept; below it, escalate.     |

This is where "form a temporary AI team" and "compute confidence" are declared —
without yet saying *how* they run.

## 7. Registries (`registry/`)

Packs reference shared, kernel-level registries:

| File                   | Declares                                             |
|------------------------|------------------------------------------------------|
| `registry/systems.yaml`| Which packs exist and are enabled.                   |
| `registry/models.yaml` | Model **adapters** (plugins). No secrets.            |
| `registry/tools.yaml`  | Tools a pack may request in `permissions.yaml`.      |
| `registry/roles.yaml`  | Roles a pack may staff in routing/workflows.         |

## 8. Rules

- A pack **must not** import vendor SDKs; it declares capabilities the kernel
  fulfills through model adapters.
- A pack **must not** contain secrets; `data/` and `private/` subfolders (and
  vault contents) are gitignored.
- `manifest.id` **must** equal the folder name.
- Existing personal/investment folders are **never destructively moved** into a
  pack; import via safe copy or an explicit source path (constitution rule 9).

## 9. Out of scope for Milestone 1

Pack discovery beyond structural validation, capability resolution, routing
decisions, memory stores, permission enforcement, and workflow execution. Those
belong to later milestones (see [`ROADMAP.md`](ROADMAP.md)).
