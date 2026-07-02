"""Dynamic Team Formation (v0 + memory guidance).

Given a TaskVector and a CapabilityGraph, choose a team template, resolve each
position to a concrete model (scoring the graph, preferring diversity), and
assemble an ExecutionPlan. Nothing is executed — this only plans.

Optionally consults a memory advisor: recorded performance nudges model choice
toward what has worked ("memory advises, the kernel decides"). The nudge is
bounded and only applies to models already qualified for a position, so it never
overrides capability/risk/template guardrails.
"""

from __future__ import annotations

from typing import List, Optional, Protocol, Set, Tuple

from ammo.kernel.capability_graph.graph import CapabilityGraph
from ammo.kernel.task_understanding.task_vector import TaskVector
from ammo.kernel.team_formation import templates as tpl
from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember


class ModelMemory(Protocol):
    """A read-only source of performance bias for model selection."""

    def bonus(self, model_id: str, role: str, tag: str,
              objective: str = "balanced") -> Tuple[float, List[str]]:
        ...


OBJECTIVES = ("balanced", "performance", "cost", "speed")
_COST_ORDER = {"cheap": 0, "standard": 1, "premium": 2}
_BIAS_CAP = 2.0  # preferences.model_bias clamp; < capability match (+3)


class TeamFormer:
    def __init__(self, graph: CapabilityGraph, memory: Optional[ModelMemory] = None,
                 binding=None, objective: str = "balanced",
                 primary: Optional[str] = None,
                 preferences: Optional[dict] = None,
                 limits: Optional[dict] = None,
                 workflows: Optional[list] = None):
        self.graph = graph
        self.memory = memory
        self.binding = binding  # optional per-system Binding (constrains selection)
        self.objective = objective if objective in OBJECTIVES else "balanced"
        # the summoning host's model (ammo.config.yaml) anchors the LEAD seat
        self.primary = primary
        # per-system optimization specs (.ammo/preferences.yaml, limits.yaml)
        self.preferences = preferences or {}
        self.limits = limits or {}
        # pack workflows.yaml: declared stage pipelines that can route the team
        self.workflows = workflows or []

    # -- public -------------------------------------------------------------

    def form(self, task: TaskVector, extra_roles: Optional[List[str]] = None) -> ExecutionPlan:
        """`extra_roles` lets an escalation (limits.yaml `add_role:X`) reinforce
        the team; they are appended AFTER the max_team_size cap on purpose."""
        template, positions, workflow_id, workflow_gate, debate = self._route(task)
        if template == "coding_standard" and task.needs_tests:
            positions.append("test_runner")

        # preferences.yaml preferred_roles: bias positions toward these — they
        # move to the front (stable), so they take the lead seat and survive a
        # max_team_size cut. No new seats are invented.
        preferred = [r for r in (self.preferences.get("preferred_roles") or [])]
        if preferred:
            rank = {role: i for i, role in enumerate(preferred)}
            positions.sort(key=lambda p: (rank.get(p, len(rank)),))

        # limits.yaml: max_team_size truncates (position order is priority order)
        max_team = self.limits.get("max_team_size")
        if max_team:
            positions = positions[: int(max_team)]

        for role in extra_roles or []:
            if role not in positions and (role in tpl.POSITION_SPEC or role in tpl.FIXED_MODELS):
                positions.append(role)

        team, notes = self._assign_models(positions, task)
        roles = [m.role for m in team]

        return ExecutionPlan(
            selected_system=(task.candidate_systems[0] if task.candidate_systems else None),
            selected_team=team,
            roles=roles,
            reasoning_summary=(
                f"Formed a '{template}' team ({len(team)} member(s)) for a "
                f"{task.risk}-risk {task.domain}/{task.intent} task"
                f"{' (memory-guided)' if self.memory and notes else ''}."
            ),
            required_tools=self._tools(template, task, roles),
            risk_controls=self._risk_controls(template, task),
            expected_outputs=self._expected_outputs(template, task, roles),
            notes=notes,
            workflow=workflow_id,
            workflow_gate=workflow_gate,
            debate=debate if debate and {debate["proposer"], debate["challenger"]} <= set(roles) else None,
        )

    # -- template selection -------------------------------------------------

    def _route(self, task: TaskVector):
        """(template_label, positions, workflow_id, workflow_gate).

        Routing order: preferences.default_template (explicit override) ->
        a pack workflow whose id matches the task's intent or a tag ->
        the domain-driven hardcoded template.
        """
        override = self.preferences.get("default_template")
        if override in tpl.TEMPLATES:
            return override, list(tpl.TEMPLATES[override]), None, None, None

        workflow = self._match_workflow(task)
        if workflow is not None:
            stages = [st for st in (workflow.get("stages") or [])
                      if st.get("role") in tpl.POSITION_SPEC
                      or st.get("role") in tpl.FIXED_MODELS]
            positions = [st["role"] for st in stages]
            if positions:
                return (f"workflow:{workflow.get('id')}", positions,
                        workflow.get("id"), workflow.get("confidence_gate"),
                        self._debate_spec(stages))

        template = self._select_template(task)
        return template, list(tpl.TEMPLATES[template]), None, None, None

    @staticmethod
    def _debate_spec(stages):
        """First stage marked `debate` becomes the challenger; the stage before
        it is the proposer. `debate: true` = 1 round; an int = that many."""
        for i, stage in enumerate(stages):
            flag = stage.get("debate")
            if flag and i > 0:
                rounds = int(flag) if isinstance(flag, int) and not isinstance(flag, bool) else 1
                return {"proposer": stages[i - 1]["role"],
                        "challenger": stage["role"],
                        "rounds": max(1, rounds)}
        return None

    def _match_workflow(self, task: TaskVector):
        """A workflow routes only on an EXACT normalized id match with the
        task's intent or one of its tags — never fuzzily (a pack declaring
        workflows must not hijack unrelated tasks)."""
        wanted = {str(task.intent or "").replace("-", "_").lower()}
        wanted |= {str(t).replace("-", "_").lower() for t in (task.tags or [])}
        for workflow in self.workflows:
            wf_id = str(workflow.get("id") or "").replace("-", "_").lower()
            if wf_id and wf_id in wanted:
                return workflow
        return None

    def _select_template(self, task: TaskVector) -> str:
        # preferences.yaml: an explicit per-system template override wins
        override = self.preferences.get("default_template")
        if override in tpl.TEMPLATES:
            return override
        if task.domain == "ops":
            return "ops_incident"
        if task.domain == "coding":
            return "coding_high_risk" if task.risk == "high" else "coding_standard"
        if task.domain == "investment":
            return "investment_research"
        if task.domain == "research":
            return "research"
        if task.risk == "low" and task.complexity in {"low", "medium"}:
            return "simple_fast"
        return "generalist"

    # -- model assignment ---------------------------------------------------

    def _assign_models(self, positions: List[str], task: TaskVector) -> Tuple[List[TeamMember], List[str]]:
        used: Set[str] = set()
        team: List[TeamMember] = []
        notes: List[str] = []
        lead = positions[0] if positions else None
        for position in positions:
            model_id, note = self._pick_model(position, task, used,
                                              is_lead=(position == lead))
            team.append(TeamMember(role=position, model=model_id))
            used.add(model_id)
            if note:
                notes.append(note)
        return team, notes

    def _static_score(self, node, spec, task: TaskVector, used: Set[str]) -> int:
        score = 0
        if spec.get("capability") and spec["capability"] in node.capabilities:
            score += 3
        if spec.get("role") and spec["role"] in node.roles:
            score += 3
        if node.warm_status == "warm":
            score += 1
        if task.risk == "high" and node.cost_class == "premium":
            score += 1
        if task.risk == "low" and node.cost_class == "cheap":
            score += 1
        if task.complexity == "low" and node.latency_class == "fast":
            score += 1

        # objective profile: same task, different optimum by what the user values
        if self.objective == "cost":
            if node.cost_class == "cheap":
                score += 2
            elif node.cost_class == "premium":
                score -= 1
        elif self.objective == "speed":
            if node.latency_class == "fast":
                score += 2
            if node.warm_status == "warm":
                score += 1
        elif self.objective == "performance":
            if node.cost_class == "premium":
                score += 2

        if node.id in used:
            score -= 2  # prefer a different model for each seat
        return score

    def _memory_tag(self, task: TaskVector) -> str:
        # prefer the selected system (per-directory memory), else the domain
        return task.candidate_systems[0] if task.candidate_systems else task.domain

    def _candidates(self):
        """Enabled nodes, restricted to the bound model set when a binding exists."""
        nodes = self.graph.enabled()
        if self.binding and self.binding.model_ids:
            allowed = set(self.binding.model_ids)
            restricted = [n for n in nodes if n.id in allowed]
            if restricted:  # fall back to all if the binding can't be honored
                nodes = restricted
        # limits.yaml: cost_class_max caps how expensive members may be
        cost_max = self.limits.get("cost_class_max")
        if cost_max in _COST_ORDER:
            capped = [n for n in nodes
                      if _COST_ORDER.get(n.cost_class, 1) <= _COST_ORDER[cost_max]]
            if capped:  # fall back to all rather than leave seats unfillable
                nodes = capped
        return nodes

    def _pick_model(self, position: str, task: TaskVector, used: Set[str],
                    is_lead: bool = False) -> Tuple[str, Optional[str]]:
        if position in tpl.FIXED_MODELS:
            return tpl.FIXED_MODELS[position], None

        # an explicit bound team pins this role's model directly
        if self.binding:
            bound = self.binding.team_map.get(position)
            if bound:
                return bound, f"{position}: bound to {bound}"

        spec = tpl.POSITION_SPEC[position]
        static = []
        final = []
        for node in self._candidates():
            base = self._static_score(node, spec, task, used)
            static.append((base, node.id))

            memory_bonus = 0.0
            reasons: List[str] = []
            # guardrail: memory only nudges models already qualified for the seat,
            # and the bonus (<=2) can never outweigh a capability match (+3).
            qualified = (
                (spec.get("capability") and spec["capability"] in node.capabilities)
                or (spec.get("role") and spec["role"] in node.roles)
            )
            if self.memory and qualified:
                memory_bonus, reasons = self.memory.bonus(
                    node.id, position, self._memory_tag(task), objective=self.objective
                )
            # primary anchors the lead seat — but only when qualified for it,
            # and weaker than a capability match (+3), so it's a tie-breaker.
            primary_bonus = 0.0
            if is_lead and qualified and node.id == self.primary:
                primary_bonus = 1.5
                reasons = list(reasons) + ["primary model (summoning host)"]
            # preferences.yaml: per-system model bias (qualified-only, clamped)
            pref_bonus = 0.0
            if qualified:
                try:
                    raw_bias = float(self.preferences.get("model_bias", {}).get(node.id, 0) or 0)
                except (TypeError, ValueError):
                    raw_bias = 0.0
                if raw_bias:
                    pref_bonus = max(-_BIAS_CAP, min(_BIAS_CAP, raw_bias))
                    reasons = list(reasons) + ["system preference (model_bias)"]
            if any(c in node.capabilities
                   for c in self.preferences.get("preferred_capabilities") or []):
                pref_bonus += 1.0
            final.append((base + memory_bonus + primary_bonus + pref_bonus,
                          node.id, reasons))

        if not final:
            return "unassigned", None

        static.sort(key=lambda item: (-item[0], item[1]))
        final.sort(key=lambda item: (-item[0], item[1]))
        static_pick = static[0][1]
        picked_score, picked_id, picked_reasons = final[0]

        note: Optional[str] = None
        if picked_reasons:
            if picked_id != static_pick:
                note = f"{position}: {picked_id} over {static_pick} — {'; '.join(picked_reasons)}"
            else:
                note = f"{position}: {picked_id} — {'; '.join(picked_reasons)}"
        return picked_id, note

    # -- derived plan fields ------------------------------------------------

    def _lookup_template(self, template: str, task: TaskVector) -> str:
        """Workflow-routed teams inherit the domain template's tools/risk
        controls (domain governance is a property of the domain, not the
        team shape)."""
        if template.startswith("workflow:"):
            return self._select_template(task)
        return template

    def _tools(self, template: str, task: TaskVector, roles: List[str]) -> List[str]:
        template = self._lookup_template(template, task)
        tools = set(task.required_tools) | set(tpl.TEMPLATE_TOOLS.get(template, []))
        if "test_runner" in roles:
            tools.add("shell.run")
        ordered = [t for t in tpl.TOOL_ORDER if t in tools]
        ordered += sorted(t for t in tools if t not in tpl.TOOL_ORDER)
        return ordered

    def _risk_controls(self, template: str, task: TaskVector) -> List[str]:
        template = self._lookup_template(template, task)
        controls = list(tpl.TEMPLATE_RISK_CONTROLS.get(template, []))
        if task.needs_tests and "require_tests" not in controls:
            controls.append("require_tests")
        controls += tpl.BASE_RISK_CONTROLS
        # de-duplicate, preserve order
        seen: Set[str] = set()
        return [c for c in controls if not (c in seen or seen.add(c))]

    def _expected_outputs(self, template: str, task: TaskVector, roles: List[str]) -> List[str]:
        if template in tpl.TEMPLATE_OUTPUTS:
            return list(tpl.TEMPLATE_OUTPUTS[template])
        if template in {"coding_high_risk", "coding_standard"}:
            outputs = ["code_diff"]
            if "test_runner" in roles:
                outputs.append("test_results")
            return outputs
        return [task.output_type]


def form_team(task: TaskVector, graph: CapabilityGraph) -> ExecutionPlan:
    """Convenience wrapper."""
    return TeamFormer(graph).form(task)
