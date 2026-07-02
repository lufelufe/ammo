# Memory Dream — consolidation playbook for AMMO's memory layers

Periodically reorganize AMMO's memory so it stays a *help* instead of decaying
into noise: merge duplicates, resolve contradictions with the newest value,
remove references to things that no longer exist, and distill repeated patterns
into compact insights. Adapted from the Managed-Agents "Dreams" idea to AMMO's
manual, git-based environment.

**Prime directive: inputs are never destroyed.** Dry-run first; apply behind an
explicit flag with a backup; commit in logical units so any step can be
reverted; review outputs before adopting (consolidation can hallucinate).

## AMMO's memory layers (what a dream pass covers)

| Layer | Contents | Dream treatment |
|---|---|---|
| Rule layer — `docs/AMMO_MANIFESTO.md` (§5 canonical) → `AGENTS.md` (working copy) | The constitution & conventions | **Not a dream target.** It is the reference that decides which duplicate survives. |
| Decision records — `docs/HERMES_INTEGRATION.md`, ROADMAP delivery log | Why choices were made | History is the point — keep rationale. Only fix *stale facts* (dead symbols, renamed files). |
| Working indexes — `docs/BACKLOG.md` | Open risks/decisions | Keep **lean**: open items only; move ✅resolved lines out (git/ROADMAP already hold the history). |
| Quantitative memory — `memory/ammo.sqlite` | runs, model_performance, team_synergy | Merge legacy domain-keyed rows into system-keyed ones; recompute aggregates over a recent window (all-time averages let stale runs dominate); delete orphan rows for models no longer in `registry/models.yaml`. |
| Run artifacts — `runtime/runs/` | Per-run evidence | After mining into aggregates, prune old runs (no rotation exists otherwise). |
| Role workspaces — `systems/<sys>/roles/<role>/` | Append-only journals | Distill into a short per-role insights file + keep the last N entries; raw journals are noise if replayed wholesale. |

## The four steps

1. **Mine** — scan recent runs/journals for repeated corrections, confirmed
   approaches, and new facts. Ignore one-off debug noise.
2. **Consolidate** — merge findings into the existing layer. Convert relative
   dates to absolute. Resolve contradictions in favor of the newest value.
   Remove (or re-verify) statements pointing at files/symbols/flags that no
   longer exist.
3. **Dedup & Resolve** — remove cross-layer duplication. **A rule defined by a
   higher layer is deleted from lower layers silently** (at most one pointer
   sentence to where it lives). If a contradiction is genuine, ask the user.
4. **Prune & Index** — keep indexes lean; delete completed/valueless entries;
   regenerate any generated listings so they match the filesystem.

## Deliverable hygiene (what stays OUT of consolidated files)

- Meta-notes about deduplication itself ("this is defined by X, not repeated
  here") — just delete the duplicate silently.
- Session IDs, repeat counts, who-said-what. Technical causality that changes
  behavior ("A breaks B, so do C") **stays**; provenance chatter goes.
- Exception: *decision records* keep their rationale — that is their job. This
  hygiene applies to working indexes and distilled insights, not to
  `HERMES_INTEGRATION.md`-style documents.

## Checklist

- [ ] Relative dates → absolute dates
- [ ] Lower layers no longer restate higher-layer rules (and no meta-note left behind)
- [ ] Contradictions resolved to the newest value (ask the user when genuinely ambiguous)
- [ ] No references to nonexistent files/symbols/models (verify or delete)
- [ ] Indexes lean (BACKLOG = open items only; memory aggregates windowed; orphan rows gone)
- [ ] Changes committed in logical units, review possible before adoption (no push without instruction)
- [ ] Output reviewed before adoption — consolidation output is not trusted blindly

## Triggers

- Right after a large refactor / registry change (renamed or removed models
  leave orphan aggregates — highest priority).
- Accumulation: ~20–30 recorded runs, or when `docs/BACKLOG.md` / role journals
  visibly bloat.
- The user asks for a "dream" / memory consolidation.

## Status

Adopted as policy (see `AGENTS.md` → Memory hygiene) **and automated**:
`ammo dream` implements the quantitative-memory pass — `src/ammo/dream/`.

- **Dry-run by default**: `ammo dream` reports what would change; `--apply`
  performs it after copying the DB to `ammo.sqlite.bak`.
- **Consolidate**: rebuilds `model_performance`/`team_synergy` from the last
  `--window N` runs (default 50), re-deriving tags (system, else domain) so
  legacy domain-keyed rows merge; per-model cost/token averages carry over from
  a pre-rebuild snapshot (runs don't store per-model usage).
- **Dedup**: drops rows for models no longer in `registry/models.yaml`.
- **Prune**: deletes run rows + `runtime/runs/` dirs beyond the window.
- **Distill**: role journals over `--journal-keep` (default 20) are trimmed to
  the most recent entries plus an `insights.md` summary.

The doc-layer dream (specs/README/BACKLOG rot) remains a manual pass — code can
consolidate numbers deterministically, but prose consolidation needs review.
