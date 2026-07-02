"""Render the files of a system pack (`.ammo/*` + `system.md`).

Used to scaffold a new in-tree pack (`new-system`) or to attach an external
directory as a mounted pack (`connect`). Output is deterministic English text,
and every produced pack satisfies the System Pack Contract (valid apiVersion,
manifest id == folder, and only registry-known roles/tools).
"""

from __future__ import annotations

from typing import Dict, List, Optional


def _block_list(items: List[str], indent: int) -> str:
    pad = " " * indent
    if not items:
        return f"{pad}[]"
    return "\n".join(f'{pad}- "{it}"' for it in items)


def render_pack_files(
    system_id: str,
    *,
    source_path: Optional[str] = None,
    writable: bool = True,
    tools: Optional[List[str]] = None,
    description: Optional[str] = None,
) -> Dict[str, str]:
    """Return {relative_path: content} for a complete pack."""
    mounted = source_path is not None
    tools = tools if tools is not None else (["fs.read", "fs.write"] if writable else ["fs.read"])
    description = description or (
        f"Connected system pack backed by {source_path}." if mounted
        else f"System pack '{system_id}'."
    )

    read_scope = [source_path] if mounted else [f"systems/{system_id}"]
    write_scope = [f"memory/{system_id}", f"runtime/{system_id}"]
    if mounted and writable:
        write_scope = [source_path] + write_scope

    manifest_extra = ""
    if mounted:
        manifest_extra = (
            f'source_path: "{source_path}"\n'
            f"mounted: true\n"
            f"writable: {str(writable).lower()}\n"
        )

    manifest = (
        "# manifest.yaml — pack identity (generated).\n"
        "apiVersion: ammo/v1\n"
        "kind: SystemPack\n"
        f"id: {system_id}\n"
        f"name: {system_id}\n"
        "version: 0.0.0\n"
        f"status: {'connected' if mounted else 'scaffold'}\n"
        "entrypoint: system.md\n"
        f"description: >-\n  {description}\n"
        f"tags: [{system_id}]\n"
        f"{manifest_extra}"
        "capabilities: []\n"
    )

    routing = (
        "# routing.yaml — relevance signals (generated; edit to tune).\n"
        "apiVersion: ammo/v1\n"
        "kind: Routing\n"
        f"system: {system_id}\n"
        "priority: 50\n"
        "match:\n"
        "  intents: []\n"
        f"  keywords: [{system_id}]\n"
        "  examples: []\n"
        "default_roles: [analyst, synthesizer]\n"
        "escalation:\n"
        "  on_low_confidence: add_role:critic\n"
    )

    memory_map = (
        "# memory_map.yaml — learning memory (generated).\n"
        "apiVersion: ammo/v1\n"
        "kind: MemoryMap\n"
        f"system: {system_id}\n"
        f"namespace: {system_id}\n"
        "stores:\n"
        "  episodic:\n"
        "    kind: run-history\n"
        f"    location: memory/{system_id}/episodic\n"
        "  semantic:\n"
        "    kind: distilled-knowledge\n"
        f"    location: memory/{system_id}/semantic\n"
        "feedback:\n"
        "  writes: [outcome, confidence, team_composition]\n"
        "retention:\n"
        "  episodic: 90d\n"
        "  semantic: keep\n"
    )

    permissions = (
        "# permissions.yaml — security boundary (generated). No secrets here.\n"
        "apiVersion: ammo/v1\n"
        "kind: Permissions\n"
        f"system: {system_id}\n"
        "filesystem:\n"
        "  read:\n"
        f"{_block_list(read_scope, 4)}\n"
        "  write:\n"
        f"{_block_list(write_scope, 4)}\n"
        "vaults:\n"
        "  read: []\n"
        "  write: []\n"
        "network:\n"
        "  allow: false\n"
        "tools:\n"
        f"  allow: [{', '.join(tools)}]\n"
        "models:\n"
        '  allow: ["*"]\n'
        "roles:\n"
        "  allow: [analyst, synthesizer, critic]\n"
    )

    workflows = (
        "# workflows.yaml — declarative task templates (generated).\n"
        "apiVersion: ammo/v1\n"
        "kind: Workflows\n"
        f"system: {system_id}\n"
        "workflows:\n"
        "  - id: handle\n"
        "    description: Default single-pass handling.\n"
        "    stages:\n"
        "      - role: analyst\n"
        "        does: gather-and-structure\n"
        "      - role: synthesizer\n"
        "        does: compose-result\n"
        "    confidence_gate: 0.6\n"
    )

    if mounted:
        body = (
            f"# {system_id} — System Pack (connected)\n\n"
            f"Mounted external directory: `{source_path}`\n\n"
            "## Boundaries\n"
            f"- Access is scoped to the mounted path{'' if writable else ' (read-only)'}.\n"
            "- The original directory is referenced in place — never moved or copied.\n"
            "- Holds no secrets; credentials are resolved at runtime by adapters.\n\n"
            "## Status\n"
            "Connected (generated): the contract is declared; behavior is not implemented.\n"
        )
    else:
        body = (
            f"# {system_id} — System Pack\n\n"
            f"{description}\n\n"
            "## Boundaries\n"
            f"- Reads within `systems/{system_id}`; writes to its `memory/` and `runtime/`.\n"
            "- Holds no secrets; credentials are resolved at runtime by adapters.\n\n"
            "## Status\n"
            "Scaffold (generated): the contract is declared; behavior is not implemented.\n"
        )

    preferences = (
        "# preferences.yaml — per-system model/team bias (optional; safe defaults).\n"
        "apiVersion: ammo/v1\n"
        "kind: Preferences\n"
        f"system: {system_id}\n"
        "preferred_capabilities: []   # e.g. [coding] or [research, analysis]\n"
        "preferred_roles: []          # bias team positions toward these\n"
        "model_bias: {}               # model_id -> advisory hint\n"
        "default_template: null       # override team template, e.g. coding_high_risk\n"
    )
    verification = (
        "# verification.yaml — what counts as evidence/success here (optional).\n"
        "apiVersion: ammo/v1\n"
        "kind: Verification\n"
        f"system: {system_id}\n"
        "success_evidence: []   # evidence kinds that raise confidence (e.g. test_result, citation)\n"
        "required_outputs: []   # outputs a complete result must include\n"
        "test_command: null     # e.g. \"python -m pytest -q\" — run for REAL in the sandbox\n"
    )
    limits = (
        "# limits.yaml — per-system caps and gates (optional).\n"
        "apiVersion: ammo/v1\n"
        "kind: Limits\n"
        f"system: {system_id}\n"
        "max_team_size: 5\n"
        "confidence_gate: 0.6   # accept threshold; below -> escalate\n"
        "cost_class_max: premium\n"
        "escalation: add_role:critic\n"
    )
    context = (
        f"# {system_id} — Operating context\n\n"
        "Guidance injected to workers operating in this system: conventions,\n"
        "do/don'ts, and what a good result looks like here. (Edit freely.)\n"
    )
    ammoignore = (
        "# Paths AMMO should ignore within this system (one glob per line).\n"
        "# Protect secrets and noise. Examples:\n"
        "# .env\n"
        "# *.key\n"
        "# node_modules/\n"
    )

    return {
        ".ammo/manifest.yaml": manifest,
        ".ammo/routing.yaml": routing,
        ".ammo/memory_map.yaml": memory_map,
        ".ammo/permissions.yaml": permissions,
        ".ammo/workflows.yaml": workflows,
        ".ammo/preferences.yaml": preferences,
        ".ammo/verification.yaml": verification,
        ".ammo/limits.yaml": limits,
        "system.md": body,
        "context.md": context,
        ".ammoignore": ammoignore,
    }
