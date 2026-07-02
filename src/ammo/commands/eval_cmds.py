"""ammo CLI handlers — eval cmds (split from cli.py)."""

import argparse
import json
from datetime import datetime, timezone
from ammo.kernel.evaluation import EvaluationEngine
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems


def _eval_compare(root) -> int:
    """Diff the two most recent eval reports — the improvement trend."""
    reports_dir = root / "runtime" / "reports"
    files = sorted(reports_dir.glob("eval-*.json")) if reports_dir.is_dir() else []
    if len(files) < 2:
        print("Need at least two eval reports to compare — run `ammo eval --mock` again later.")
        return 1
    prev, curr = (json.loads(f.read_text(encoding="utf-8")) for f in files[-2:])
    print(f"eval trend: {files[-2].name} ({prev.get('mode', 'static')}) -> "
          f"{files[-1].name} ({curr.get('mode', 'static')})")
    delta = curr["cases_passed"] - prev["cases_passed"]
    print(f"  cases fully correct: {prev['cases_passed']}/{prev['cases_total']} -> "
          f"{curr['cases_passed']}/{curr['cases_total']} ({delta:+d})")
    for metric, tally in curr["metric_totals"].items():
        before = prev["metric_totals"].get(metric, {}).get("passed", 0)
        print(f"  {metric}: {before} -> {tally['passed']} ({tally['passed'] - before:+d})")
    prev_fail = {c["id"] for c in prev["cases"] if not c["passed"]}
    curr_fail = {c["id"] for c in curr["cases"] if not c["passed"]}
    for cid in sorted(prev_fail - curr_fail):
        print(f"  fixed: {cid}")
    for cid in sorted(curr_fail - prev_fail):
        print(f"  regressed: {cid}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    if getattr(args, "compare", False):
        return _eval_compare(root)
    if not args.mock:
        print("Only --mock eval is available in this milestone (no real models).")
        return 2

    from ammo.evalsuite import EvalSuite, load_cases

    cases = load_cases(root / "evals")
    if not cases:
        print(f"No eval cases found under {root / 'evals'}.")
        return 1

    memory = None
    mode = "static"
    if getattr(args, "with_memory", False):
        db = root / "memory" / "ammo.sqlite"
        if db.is_file():
            memory = MemoryAdvisor.from_store(MemoryStore(db))
            mode = "with-memory"
        else:
            print("note: no run memory yet — falling back to the static baseline")

    report = EvalSuite(root=root, memory=memory).run(cases)

    print(f"AMMO eval (mock, {mode}) — {report.cases_passed}/{len(report.results)} cases fully correct")
    for metric, tally in report.metric_totals().items():
        print(f"  {metric}: {tally['passed']}/{tally['total']}")
    for result in report.results:
        if not result.passed:
            failed = [m for m, ok in result.metrics.items() if not ok]
            print(f"  ! {result.id} failed: {', '.join(failed)}  observed={result.observed}")

    now = datetime.now(timezone.utc)
    reports_dir = root / "runtime" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"eval-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(
        json.dumps({"created_at": now.isoformat(), "mode": mode, **report.to_dict()},
                   ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"report: {path}")
    return 0 if report.all_passed else 1


def _cmd_eval_system(args: argparse.Namespace) -> int:
    report = EvaluationEngine().evaluate(find_ammo_root(), args.system_id)
    print(report.to_card())
    return 1 if report.health == "at_risk" else 0


def _cmd_eval_systems(_args: argparse.Namespace) -> int:
    root = find_ammo_root()
    engine = EvaluationEngine()
    systems = SystemPackLoader(root).available()
    if not systems:
        print("No systems to evaluate.")
        return 0
    worst_ok = True
    for system_id in systems:
        report = engine.evaluate(root, system_id)
        print(f"- {system_id}: {report.health}")
        if report.health == "at_risk":
            worst_ok = False
    return 0 if worst_ok else 1
