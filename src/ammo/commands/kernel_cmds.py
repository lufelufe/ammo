"""ammo CLI handlers — kernel cmds (split from cli.py)."""

import argparse
import json
from ammo.kernel.capability_graph import CapabilityGraph, score_models, task_needs
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.paths import find_ammo_root
from ammo.commands.common import _understand, _load_binding, _load_memory_advisor, _load_pack_for_task, _load_primary, _load_role_assignments, _resolve_objective


def _cmd_analyze(args: argparse.Namespace) -> int:
    vector = TaskAnalyzer().analyze(args.text)
    print(json.dumps(vector.to_dict(), ensure_ascii=False, indent=2))
    return 0


def _cmd_list_models(_args: argparse.Namespace) -> int:
    graph = CapabilityGraph.from_registry(find_ammo_root())
    if not graph.nodes:
        print("No models found in registry/models.yaml.")
        return 0
    print("Models (capability graph):")
    for node in graph.nodes:
        state = "enabled" if node.enabled else "disabled"
        print(
            f"  - {node.id}  [{node.provider}]  "
            f"roles={','.join(node.roles) or '-'}  "
            f"caps={','.join(node.capabilities) or '-'}  "
            f"ctx={node.context_window}  cost={node.cost_class}  "
            f"lat={node.latency_class}  {node.warm_status}  ({state})"
        )
    return 0


def _cmd_score_models(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    graph = CapabilityGraph.from_registry(root)
    task = _understand(root, args)
    ranked = score_models(task, graph)

    primary, secondary, caps = task_needs(task)
    print(f"Task: {task.domain} / {task.intent}  (risk {task.risk}, ctx {task.context_size})")
    print(f"  needs roles: {', '.join(sorted(primary | secondary)) or '(none)'}")
    print(f"  needs capabilities: {', '.join(sorted(caps)) or '(none)'}")
    print("Ranked models:")
    for rank, scored in enumerate(ranked, start=1):
        reasons = ", ".join(scored.reasons) or "-"
        print(f"  {rank:2}. {scored.model_id:20} score {scored.score:>3}  [{reasons}]")
    return 0


def _cmd_plan_team(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    graph = CapabilityGraph.from_registry(root)
    task = _understand(root, args)
    pack = _load_pack_for_task(root, task)
    plan = TeamFormer(
        graph, memory=_load_memory_advisor(root, args), binding=_load_binding(root, task),
        objective=_resolve_objective(root, args), primary=_load_primary(root),
        role_assignments=_load_role_assignments(root),
        preferences=pack.preferences if pack else None,
        limits=pack.limits if pack else None,
        workflows=pack.workflow_list if pack else None,
    ).form(task)
    print(json.dumps(plan.to_dict(), ensure_ascii=False, indent=2))
    return 0
