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
[1/4] Host: claude-code — proposing claude_a_planner (via claude-code) as primary
[2/4] Usable models: claude_a_planner, claude_b_critic, codex_builder
[3/4] Workspace: connecting grants filesystem access — `ammo connect <path>`
[4/4] Default objective: balanced / performance / cost / speed
✓ Saved ammo.config.yaml (machine-local, git-ignored)

$ ammo start                     (every later summon)
host: claude-code  primary: claude_a_planner via claude-code
models: …  objective: balanced  systems: …  memory: N run(s)
ready — `ammo run --mock|--real "..."`, `ammo status` anytime.
```

The config (`ammo.config.yaml` at the AMMO root) holds host, primary model,
preferred model set, and the default `--optimize` objective — `run`/`plan-team`
use the configured objective when no flag is given. No secrets.

## Per-host shims

| Host | Shim |
|---|---|
| Terminal | none — `ammo start` (or `python -m ammo start`) |
| Claude Code / Codex / other agents | An instruction in the auto-loaded guide (`AGENTS.md` → "Summon"): when the user says "ammo", run `python -m ammo start --host <id>`. Optionally a slash command in the host's local config. |
| New host | Add one instruction line passing its `--host` id; `detect_host` env fingerprints are only a fallback. |

Host detection order: explicit `--host` flag (shim) → environment fingerprints
(`CLAUDECODE`/`CLAUDE_CODE_ENTRYPOINT` → claude-code, `CODEX_*` → codex) →
`terminal`.
