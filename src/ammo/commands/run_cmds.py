"""ammo CLI handlers — run cmds (split from cli.py)."""

import argparse
import json
import sys
from datetime import datetime, timezone
from ammo.adapters import MockAdapter, RealAdapterFactory
from ammo.kernel.capability_graph import CapabilityGraph, score_models, task_needs
from ammo.kernel.confidence import ConfidenceEngine
from ammo.kernel.executor import Runner, RunStore
from ammo.kernel.task_understanding import TaskAnalyzer
from ammo.kernel.team_formation import TeamFormer
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root
from ammo.roles import RoleWorkspace
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems
from ammo.commands.common import _understand, _load_binding, _load_memory_advisor, _load_pack_for_task, _load_primary, _resolve_objective, _role_memory


def _cmd_run(args: argparse.Namespace) -> int:
    if args.mock and args.real:
        print("Error: choose either --mock or --real, not both.")
        return 2
    if not args.mock and not args.real:
        print("Error: specify --mock (offline) or --real (call authenticated CLIs).")
        return 2

    root = find_ammo_root()
    graph = CapabilityGraph.from_registry(root)
    task = _understand(root, args)
    pack = _load_pack_for_task(root, task)
    former = TeamFormer(
        graph, memory=_load_memory_advisor(root, args), binding=_load_binding(root, task),
        objective=_resolve_objective(root, args), primary=_load_primary(root),
        preferences=pack.preferences if pack else None,
        limits=pack.limits if pack else None,
        workflows=pack.workflow_list if pack else None,
    )
    plan = former.form(task)

    # P2: consensus sampling — the lead seat answered by N independent models
    n_consensus = int(getattr(args, "consensus", 0) or 0)
    if n_consensus >= 2 and plan.selected_team:
        lead_role = plan.roles[0]
        lead_model = plan.selected_team[0].model
        alts = former.alternates(lead_role, task, exclude={lead_model},
                                 k=n_consensus - 1)
        if alts:
            plan.consensus = {"role": lead_role, "models": alts}

    if args.real:
        factory = RealAdapterFactory(root=root, allow_paid=args.allow_paid)
        mode = "real"
    else:
        factory = lambda model_id: MockAdapter(model_id)  # noqa: E731
        mode = "mock"
    def _execute(current_plan):
        """One execute→enforce-tools→assess pass (used again by self-heal)."""
        result = Runner(factory, mode=mode).run(
            current_plan, task,
            system_context=(pack.context or "") if pack else "",
            role_context=_role_memory(root, current_plan.selected_system, current_plan.roles),
            grounding=(grounding.text if grounding else ""),
        )
        # grounding reads are real evidence — attach to the lead response so the
        # Confidence Engine counts what was actually read
        if grounding and grounding.evidence and result.responses:
            result.responses[0].evidence.extend(grounding.evidence)

        # tool execution + permission enforcement: workers' declared tools are
        # gated against permissions.yaml + .ammoignore, then (safely) executed.
        permitted = denied = 0
        sandbox = None
        if current_plan.selected_system:
            try:
                import tempfile

                from ammo.tools import PermissionGate, Sandbox, ToolExecutor

                if args.execute_tools:
                    sandbox_base = root / "runtime" / "sandbox"
                    sandbox_base.mkdir(parents=True, exist_ok=True)
                    sandbox = Sandbox(tempfile.mkdtemp(dir=str(sandbox_base)))

                tool_pack = pack or SystemPackLoader(root).load(current_plan.selected_system)
                executor = ToolExecutor(PermissionGate.from_pack(root, tool_pack), sandbox=sandbox)
                for response in result.responses:
                    for evidence in executor.run_all(response.tool_requests):
                        response.evidence.append(evidence)
                        if evidence.ok:
                            permitted += 1
                        else:
                            denied += 1
            except RegistryError:
                pass

        # P3: the test_runner seat runs the system's DECLARED test command for
        # real inside the sandbox — test_result evidence becomes measured fact
        if sandbox is not None and "test_runner" in current_plan.roles and pack:
            test_command = (pack.verification or {}).get("test_command")
            if test_command:
                import shlex

                from ammo.adapters.contract import Evidence
                from ammo.tools.sandbox import SandboxError

                try:
                    t_code, t_out = sandbox.run(shlex.split(str(test_command)),
                                                timeout=120)
                    t_ok = t_code == 0
                    test_ev = Evidence(
                        "test_result",
                        f"tests {'passed' if t_ok else 'failed'} "
                        f"(`{test_command}` exit {t_code})",
                        ok=t_ok, detail=(t_out or "")[-400:],
                    )
                except SandboxError as exc:
                    test_ev = Evidence("test_result", "test run blocked",
                                       ok=False, detail=str(exc))
                seat = next((r for r in result.responses
                             if r.role == "test_runner"), None)
                if seat is not None:
                    seat.evidence.append(test_ev)

        report = ConfidenceEngine().assess(
            task, current_plan, result.responses, mode=result.mode,
            verification=pack.verification if pack else None,
        )
        return result, report, sandbox, permitted, denied

    # P1 grounding: read real files into worker context before they answer.
    # Sources: explicit --read paths, else the selected system's source_path.
    grounding = None
    explicit = list(getattr(args, "read", None) or [])
    # explicit --read is an OPERATOR directive (their own repo, like `cat`) —
    # read directly. The implicit "read the connected system's source" path
    # touches an external mounted directory, so it goes through the gate.
    read_targets, gate = explicit, None
    if not read_targets and plan.selected_system and pack and pack.source_path:
        from ammo.tools.permissions import PermissionGate

        read_targets = [pack.source_path]
        try:
            gate = PermissionGate.from_pack(root, pack)
        except Exception:
            gate = None
    if read_targets:
        from ammo.tools.grounding import gather

        grounding = gather(read_targets, root, gate=gate)

    result, report, sandbox, tool_permitted, tool_denied = _execute(plan)

    # self-heal: below the system's gate with a declared `add_role:X`
    # escalation -> reinforce the team once and re-run (never loops).
    healed_from = None
    healed_role = None
    heal_limits = (pack.limits or {}) if pack else {}
    # gate precedence: limits.yaml (explicit optimization spec) -> the routed
    # workflow's own confidence_gate; escalation falls back to routing.yaml
    heal_gate = heal_limits.get("confidence_gate")
    if heal_gate is None:
        heal_gate = plan.workflow_gate
    routing_escalation = ""
    if pack:
        routing_escalation = str(((pack.routing or {}).get("escalation") or {})
                                 .get("on_low_confidence") or "")
    heal_escalation = str(heal_limits.get("escalation") or routing_escalation)
    if (heal_gate is not None and report.confidence_score < float(heal_gate)
            and heal_escalation.startswith("add_role:")):
        extra = heal_escalation.split(":", 1)[1].strip()
        if extra and extra not in plan.roles:
            healed_from, healed_role = report.confidence_score, extra
            plan = TeamFormer(
                graph, memory=_load_memory_advisor(root, args),
                binding=_load_binding(root, task),
                objective=_resolve_objective(root, args), primary=_load_primary(root),
                preferences=pack.preferences if pack else None,
                limits=pack.limits if pack else None,
                workflows=pack.workflow_list if pack else None,
            ).form(task, extra_roles=[extra])
            plan.notes.append(
                f"self-heal: confidence {healed_from} < gate {heal_gate} -> added {extra}"
            )
            result, report, sandbox, tool_permitted, tool_denied = _execute(plan)

    # economics: estimate token usage + cost (api = spend, subscription =
    # equivalent value, local = 0) and feed it into the improvement loop.
    from ammo.economics import PricingBook

    economics = PricingBook.load(root).run_economics(result.responses)
    model_usage = {
        m["model"]: {"tokens": m["input_tokens"] + m["output_tokens"], "cost": m["cost"],
                     "latency_ms": m.get("latency_ms")}
        for m in economics["by_model"]
    }

    now = datetime.now(timezone.utc)
    run_id, path = RunStore(root).save(
        input_text=args.text, task=task, plan=plan, result=result,
        confidence=report.to_dict(), economics=economics,
        sandbox=str(sandbox.dir) if sandbox else None, now=now,
    )

    with MemoryStore.open(root) as memory:
        memory.record_run(
            run_id=run_id,
            timestamp=now.isoformat(),
            domain=task.domain,
            tags=task.tags,
            selected_system=plan.selected_system,
            model_ids=[m.model for m in plan.selected_team],
            team_signature=team_signature(plan),
            confidence_score=report.confidence_score,
            total_tokens=economics["total_tokens"],
            estimated_cost=economics["estimated_cost"],
            model_usage=model_usage,
            negative_reasons=report.reasons_negative,
        )

    # role-bound working directories: traces attach to the ROLE, not the model
    if plan.selected_system:
        workspace = RoleWorkspace(root)
        for resp in result.responses:
            workspace.record(
                plan.selected_system, resp.role,
                run_id=run_id, model=resp.model, output=resp.output,
                evidence=[e.to_dict() for e in resp.evidence],
                timestamp=now.isoformat(),
            )

    if grounding and grounding.files_read:
        print(f"grounding: read {len(grounding.files_read)} file(s)"
              + (" (truncated to budget)" if grounding.truncated else ""))
    if plan.consensus:
        print(f"consensus: {plan.consensus['role']} sampled by "
              f"{1 + len(plan.consensus['models'])} models "
              f"({', '.join(plan.consensus['models'])} as alternates)")
    if plan.debate:
        print(f"debate: {plan.debate['proposer']} ⟷ {plan.debate['challenger']} "
              f"({plan.debate.get('rounds', 1)} round(s))")
    print(f"run_id: {run_id}")
    print(f"judge it (feeds learning): ammo feedback {run_id} good|bad")
    print(f"output: {path}")
    print(f"mode: {mode}")
    if args.real and getattr(factory, "resolutions", None):
        print(f"adapters: {factory.real_count}/{len(factory.resolutions)} real")
        for model_id, (kind, provider) in factory.resolutions.items():
            via = f" via {provider}" if kind == "real" and provider else ""
            print(f"  - {model_id}: {kind}{via}")
    print(f"system: {plan.selected_system}  team: {', '.join(plan.roles)}")
    if tool_permitted or tool_denied:
        print(f"tools: {tool_permitted} permitted, {tool_denied} denied (enforced)")
    if sandbox is not None:
        print(f"sandbox: {sandbox.dir} "
              f"(os-isolation: {sandbox.isolation or 'none — allowlist shell only'})")
    print(
        f"economics: {economics['model_count']} model(s), "
        f"{economics['total_tokens']} tokens, "
        f"~${economics['estimated_cost']:.4f} {economics['currency']}"
        + (f"  [unpriced: {', '.join(economics['unpriced_models'])}]"
           if economics["unpriced_models"] else "")
    )
    print(f"confidence: {report.confidence_score} ({report.confidence_band})")
    if healed_from is not None:
        print(f"self-heal: escalated (+{healed_role}) after gate miss — "
              f"confidence {healed_from} -> {report.confidence_score}")
    # triage: failure signals become diagnoses with concrete fixes
    from ammo.triage import diagnose_run

    for diagnosis in diagnose_run(result.responses, economics=economics,
                                  system_id=plan.selected_system, mode=result.mode):
        print(diagnosis.to_text())
    # acceptance threshold: limits.yaml, else the routed workflow's gate
    gate = (pack.limits or {}).get("confidence_gate") if pack else None
    if gate is None:
        gate = plan.workflow_gate
    if gate is not None and report.confidence_score < float(gate):
        escalation = ((pack.limits or {}).get("escalation") if pack else None)             or routing_escalation or "review"
        print(f"gate: below the system confidence_gate ({gate}) — escalation: {escalation}")
    print(f"final: {result.final_output}")

    if args.show_confidence:
        print()
        print(report.to_card())
    return 0


def _cmd_show_run(args: argparse.Namespace) -> int:
    store = RunStore(find_ammo_root())
    try:
        summary = store.load_summary(args.run_id)
    except FileNotFoundError:
        print(f"Error: run '{args.run_id}' not found under {store.runs_dir}")
        return 1
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def _cmd_promote(args: argparse.Namespace) -> int:
    from ammo.tools.promote import PromoteError, plan_promotion

    try:
        report = plan_promotion(find_ammo_root(), args.run_id, to=args.to,
                                apply=args.apply)
    except PromoteError as exc:
        print(f"promote: {exc}", file=sys.stderr)
        return 1
    print(report.to_text())
    return 0
