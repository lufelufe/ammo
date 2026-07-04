# Summon Protocol — the word is "ammo"

AMMO can be summoned from any environment with one word: **ammo**. The summon
runs `python -m ammo start --host <id>`; the first summon is a short setup
wizard, every later summon is a one-screen ready summary.

## Design principles

1. **One word everywhere.** Terminal, Claude Code, Codex, any agent — the user
   says "ammo". Hosts differ only in a thin shim.
2. **The summoning host anchors the primary model.** Being summoned from Claude
   Code means an authenticated claude CLI exists — so its model is proposed as
   the primary seat. Same for Codex. The user confirms; nothing is assumed.
3. **Propose, don't interrogate.** Everything is detected first (host,
   providers, usable models); the wizard is at most 4 confirmations.
4. **Configured → skip.** A repeat summon never re-runs setup; it prints the
   ready summary (`ammo status`). `--reconfigure` redoes it.
5. **Permission grants stay explicit.** Non-interactive summons (agent shims)
   configure safe defaults only; connecting a workspace (filesystem access) and
   binding models are pointed to (`ammo connect`, `ammo bind`), never
   auto-applied.

## The boot sequence

```
$ ammo start                     (first summon)
[1/5] Host: claude-code — proposing claude_a_opus (via claude-code) as primary
[2/5] Usable models: claude_a_opus, claude_b_fable, codex_gpt5
[3/5] Default objective: balanced / performance / cost / speed
✓ Saved ammo.config.yaml (machine-local, git-ignored)
[4/5] Team roles — engine → model → role gates (interactive terminal only;
      agent hosts get the setup-step pointer and drive the gates as cards)
[5/5] Workspace — the directory AMMO works in: recommends previously-connected
      dirs, else asks for a path, then connects it (read-only / read-write)

$ ammo start                     (every later summon)
host: claude-code  primary: claude_a_opus via claude-code
models: …  objective: balanced  systems: …  memory: N run(s)
ready — `ammo run --mock|--real "..."`, `ammo status` anytime.
```

The config (`ammo.config.yaml` at the AMMO root) holds host, primary model,
preferred model set, the default `--optimize` objective, and the **role
assignment** — `run`/`plan-team` use the configured objective when no flag is
given. No secrets.

## Role setup step

Until the four team seats are assigned, every summon appends a **setup step**.
The summoning host owns the UI, so the step is host-aware:

- **Agent host** (claude-code, codex, …): the summon directs the host to run the
  role interview as an **engine → model → role** funnel — pick an engine (read
  readiness with `ammo roles plan --json`; a not-ready engine gets a resolve
  step), then its model, then the seat it plays — and persist with
  `ammo roles set --orchestrator <id> …`. In Claude Code this surfaces as cards.
- **Terminal**: the step points at `./ammo roles set` (numbered gate prompts).

Once `roles` exist in the config the step disappears and the ready summary shows
the assignment (`roles: orchestrator=… critic=… …`). Re-run `ammo roles set`
any time to change it. The role assignment is *authority* — the assigned model
wins its seat in team formation.

## Per-host shims

| Host | Shim |
|---|---|
| Terminal | `./ammo` launcher at the repo root (no venv activation needed), or `ammo` with the venv active |
| Claude Code | `CLAUDE.md` carries the summon line directly (`--host claude-code`) |
| Codex | reads `AGENTS.md` natively → its "Summon" section (`--host codex`) |
| Qwen / Gemini CLIs | thin pointer files `QWEN.md` / `GEMINI.md` → AGENTS.md + summon line |
| CLAUDE.md-compatible forks (GLM etc.) | covered by `CLAUDE.md` |
| New host | add a one-line pointer file in its instruction-file convention passing its `--host` id; `detect_host` env fingerprints are only a fallback. |

Host detection order: explicit `--host` flag (shim) → environment fingerprints
(`CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` → claude-code, `CODEX_*` → codex) →
`terminal`.

## Interactive mode (`ammo enter`)

`ammo enter` opens a stay-inside session: type a request and it runs, or type a
subcommand (`status`, `providers`, `feedback <id> good`, …). Configure once with
`set` — `set mock|real`, `set optimize <axis>`, `set read <path…>`,
`set show on|off` — and every subsequent request inherits it. Leave with `exit`,
`/ammo exit`, or Ctrl-D.
