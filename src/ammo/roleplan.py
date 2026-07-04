"""Role assignment — who plays which seat on your AMMO team.

The user authors a small, human-facing role assignment (orchestrator / critic /
simple worker / builder). AMMO detects the usable models, proposes a default per
slot, and the *summoning host* drives the interview UI (cards in Claude Code,
prompts in a terminal). The choice is persisted in ``ammo.config.yaml`` under
``roles`` and consulted by Dynamic Team Formation: an assigned model wins its
seat.

This layer is deliberate: the *capability graph* declares what a model CAN do;
the *role assignment* declares what a model SHALL do on this machine. The internal
kernel roles (router/analyst/synthesizer/critic/reviewer/implementer/test_runner)
are derived from the four slots automatically and shown as information — the user
never has to touch them, but may re-assign the slots any time.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional

from ammo.kernel.capability_graph.graph import CapabilityGraph

# The four user-facing slots. Order is the interview order. Each maps to the
# internal kernel roles it covers and the capability that qualifies a model.
SLOTS: List[dict] = [
    {
        "id": "orchestrator",
        "label": "Orchestrator",
        "summary": "Leads the team: understands the task, plans it, and composes the final result.",
        "internal_roles": ["router", "analyst", "synthesizer"],
        "capability": "planning",
    },
    {
        "id": "critic",
        "label": "Critic",
        "summary": "Adversarially challenges the result to expose errors before it ships.",
        "internal_roles": ["critic", "reviewer"],
        "capability": "review",
    },
    {
        "id": "worker",
        "label": "Simple worker",
        "summary": "Fast, cheap execution of straightforward sub-tasks.",
        "internal_roles": ["analyst", "synthesizer"],
        "capability": "general",
    },
    {
        "id": "builder",
        "label": "Builder",
        "summary": "Produces code and other concrete artifacts.",
        "internal_roles": ["implementer", "reviewer"],
        "capability": "coding",
    },
]

SLOT_IDS = [s["id"] for s in SLOTS]
_SLOT_BY_ID = {s["id"]: s for s in SLOTS}

# test_runner is infrastructure (a harness, not an LLM) — assigned automatically,
# shown as information only.
INFRA_ROLES = ["test_runner"]


def slot(slot_id: str) -> Optional[dict]:
    return _SLOT_BY_ID.get(slot_id)


# provider prefixes → friendly label, for rendering a member id as "provider · model".
_PROVIDER_LABEL = {
    "claude_a": "claude-a", "claude_b": "claude-b", "codex": "codex",
    "qwen": "qwen", "kimi": "kimi", "gpt_oss": "gpt-oss", "local": "local",
    "fast_worker": "local",
}


def pretty(model_id: str) -> str:
    """Render a composed member id as "provider · model" (e.g. claude_b_fable ->
    'claude-b · fable'). Unknown ids are returned unchanged."""
    if not model_id:
        return model_id
    for prefix, label in _PROVIDER_LABEL.items():
        if model_id == prefix or model_id.startswith(prefix + "_"):
            model = model_id[len(prefix):].lstrip("_") or label
            return f"{label} · {model.replace('_', '-')}"
    return model_id


# --- engine catalog (gate 1) -----------------------------------------------
# An engine is an auth context (a commercial subscription CLI, an API key, or a
# local runtime). Setup is a funnel: pick engine -> pick its model -> pick role.
ENGINES = [
    {"id": "claude-a", "label": "Claude · account A", "profile": "claude-code",
     "prefix": "claude_a_",
     "resolve": "log in: run `claude`, then `/login`"},
    {"id": "claude-b", "label": "Claude · account B", "profile": "claude-code-b",
     "prefix": "claude_b_",
     "resolve": "log in account B: `CLAUDE_CONFIG_DIR=~/.claude-b claude`, then `/login`"},
    {"id": "codex", "label": "Codex", "profile": "codex",
     "prefix": "codex",
     "resolve": "log in: `codex login`"},
    {"id": "local", "label": "Local · Ollama", "profile": "ollama",
     "prefix": None,
     "resolve": "install Ollama and pull a model: `ollama pull llama3`"},
]


def _detect_statuses():
    from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector

    return AvailabilityDetector().detect_all(DEFAULT_CATALOG)


def team_engines(root: Optional[Path] = None, *,
                 graph: Optional[CapabilityGraph] = None,
                 statuses=None) -> List[dict]:
    """Gate-1 data: each engine with its readiness and the models it offers.

    An engine that isn't ready still appears (with a resolve hint) so the user
    can fix it. Models are the enabled graph nodes carried by that engine's
    account prefix (local models come from the runtime's own report)."""
    graph = graph or CapabilityGraph.from_registry(root)
    nodes = graph.enabled()
    by_id = {n.id: n for n in nodes}
    statuses = statuses if statuses is not None else _detect_statuses()
    by_profile = {s.profile.id: s for s in statuses}

    out: List[dict] = []
    for eng in ENGINES:
        st = by_profile.get(eng["profile"])
        ready = bool(st and st.available)
        if eng["prefix"]:
            models = [n for n in nodes if n.id.startswith(eng["prefix"])]
        else:  # local runtime: only what it actually reports
            models = [by_id[i] for i in (st.models if st else []) if i in by_id]
        out.append({
            "id": eng["id"], "label": eng["label"], "ready": ready,
            "detail": (st.detail if st else "not detected"),
            "resolve": eng["resolve"], "models": models,
        })
    return out


def _qualified(node, spec: dict) -> bool:
    """A model is qualified for a slot when it declares the slot's capability or
    any of the slot's internal roles."""
    if spec["capability"] in node.capabilities:
        return True
    return any(r in node.roles for r in spec["internal_roles"])


def _candidate_score(node, spec: dict) -> tuple:
    """Rank key for proposing a default (higher first). Purely for ordering the
    interview; the user's pick always wins regardless of this score."""
    cap = 1 if spec["capability"] in node.capabilities else 0
    roles = sum(1 for r in spec["internal_roles"] if r in node.roles)
    warm = 1 if node.warm_status == "warm" else 0
    # worker prefers cheap+fast; orchestrator/critic prefer capable (premium ok)
    if spec["id"] == "worker":
        econ = (1 if node.cost_class == "cheap" else 0) + (1 if node.latency_class == "fast" else 0)
    else:
        econ = 1 if node.cost_class == "premium" else 0
    return (cap + roles, warm, econ, node.id)


@dataclass
class SlotPlan:
    slot: str
    label: str
    summary: str
    internal_roles: List[str]
    candidates: List[dict]        # [{model, qualified, warm, cost, latency, reason}]
    proposed: Optional[str]       # best default (qualified first, else best available)
    current: Optional[str]        # already-assigned model, if any


def plan_roles(
    root: Optional[Path] = None,
    *,
    graph: Optional[CapabilityGraph] = None,
    usable_models: Optional[List[str]] = None,
    current: Optional[Dict[str, str]] = None,
) -> List[SlotPlan]:
    """Build the interview: for each slot, the candidate models (usable ones,
    qualified first) and a proposed default. ``usable_models`` restricts to
    detected/available ids; when None, all enabled graph nodes are offered."""
    graph = graph or CapabilityGraph.from_registry(root)
    current = current or {}
    nodes = graph.enabled()
    if usable_models is not None:
        allow = set(usable_models)
        restricted = [n for n in nodes if n.id in allow]
        if restricted:                       # fall back to all if none detected
            nodes = restricted

    plans: List[SlotPlan] = []
    for spec in SLOTS:
        ranked = sorted(nodes, key=lambda n: _candidate_score(n, spec), reverse=True)
        candidates = []
        for n in ranked:
            q = _qualified(n, spec)
            candidates.append({
                "model": n.id,
                "qualified": q,
                "warm": n.warm_status == "warm",
                "cost": n.cost_class,
                "latency": n.latency_class,
                "reason": ("covers " + spec["capability"]) if q else "not marked "
                          + spec["capability"] + "-capable (assignable anyway)",
            })
        qualified = [c["model"] for c in candidates if c["qualified"]]
        proposed = qualified[0] if qualified else (candidates[0]["model"] if candidates else None)
        plans.append(SlotPlan(
            slot=spec["id"], label=spec["label"], summary=spec["summary"],
            internal_roles=list(spec["internal_roles"]),
            candidates=candidates, proposed=proposed,
            current=current.get(spec["id"]),
        ))
    return plans


def validate_assignments(assignments: Dict[str, str],
                         graph: Optional[CapabilityGraph] = None,
                         root: Optional[Path] = None) -> List[str]:
    """Return human-readable warnings (unknown slot, unknown/disabled model, or
    a model not registry-qualified for its slot). Never raises: role assignment
    is the user's authority — we inform, we do not block."""
    graph = graph or CapabilityGraph.from_registry(root)
    warnings: List[str] = []
    for slot_id, model_id in assignments.items():
        spec = _SLOT_BY_ID.get(slot_id)
        if spec is None:
            warnings.append(f"unknown slot '{slot_id}' (expected {', '.join(SLOT_IDS)})")
            continue
        node = graph.get(model_id)
        if node is None:
            warnings.append(f"{slot_id}: model '{model_id}' is not in the registry")
        elif not node.enabled:
            warnings.append(f"{slot_id}: model '{model_id}' is disabled")
        elif not _qualified(node, spec):
            warnings.append(
                f"{slot_id}: '{model_id}' isn't marked {spec['capability']}-capable "
                f"— assigning anyway (it will win the {slot_id} seat)")
    return warnings


def apply_roles(root: Path, assignments: Dict[str, str],
                *, graph: Optional[CapabilityGraph] = None):
    """Persist role assignments into ammo.config.yaml. The orchestrator's model
    also becomes ``primary_model`` (lead-seat anchor) for coherence. Returns
    (config, warnings)."""
    from ammo.config import AmmoConfig, load_config, save_config

    clean = {k: v for k, v in assignments.items() if k in SLOT_IDS and v}
    warnings = validate_assignments(clean, graph=graph, root=root)

    config = load_config(root) or AmmoConfig()
    merged = dict(config.roles)
    merged.update(clean)
    config.roles = merged
    if merged.get("orchestrator"):
        config.primary_model = merged["orchestrator"]
    save_config(root, config)
    return config, warnings


def internal_mapping(assignments: Dict[str, str]) -> List[dict]:
    """Informational view: which model covers each internal kernel role, derived
    from the four slots. Slot priority resolves overlaps (e.g. analyst is covered
    by orchestrator before worker)."""
    rows: List[dict] = []
    for spec in SLOTS:
        model = assignments.get(spec["id"])
        rows.append({
            "slot": spec["id"], "label": spec["label"], "model": model,
            "internal_roles": list(spec["internal_roles"]),
        })
    return rows
