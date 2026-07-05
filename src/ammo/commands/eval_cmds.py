"""ammo CLI handlers — eval cmds (split from cli.py)."""

import argparse
import json
from datetime import datetime, timezone
from ammo.kernel.evaluation import EvaluationEngine
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root
from ammo.registry import RegistryError, SystemPackLoader, enabled_systems


def _eval_compare(root) -> int:
    """The improvement curve: every stored report as a series, then the diff
    of the two most recent ones."""
    reports_dir = root / "runtime" / "reports"
    files = sorted(reports_dir.glob("eval-*.json")) if reports_dir.is_dir() else []
    if len(files) < 2:
        print("Need at least two eval reports to compare — run `ammo eval --mock` again later.")
        return 1
    print(f"eval history ({len(files)} reports):")
    for f in files:
        r = json.loads(f.read_text(encoding="utf-8"))
        stamp = f.stem.replace("eval-", "")
        print(f"  {stamp}  {r.get('mode', 'static'):12} "
              f"{r['cases_passed']}/{r['cases_total']}")
    prev, curr = (json.loads(f.read_text(encoding="utf-8")) for f in files[-2:])
    print(f"eval trend: {files[-2].name} ({prev.get('mode', 'static')}) -> "
          f"{files[-1].name} ({curr.get('mode', 'static')})")
    if prev.get("mode") != curr.get("mode"):
        print("  note: the two latest reports ran in DIFFERENT modes — "
              "pass-rate deltas mix baseline and learning effects")
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


def _stat_label(model_stats, model_id: str, tag: str) -> str:
    row = model_stats.get((model_id, tag))
    if not row or not (row.get("attempts") or 0):
        return f"{model_id}: no record"
    return (f"{model_id}: {row['successes']}/{row['attempts']} success "
            f"in {tag}")


def _eval_learning(root) -> int:
    """The learning curve, measured directly: run every case through the
    static baseline AND through accumulated memory, and show what the memory
    actually changed — per seat, with the recorded performance that justifies
    each swap. This is the readout that turns 'AMMO learns' into a number."""
    from ammo.evalsuite import EvalSuite, load_cases
    from ammo.memory import MemoryAdvisor

    cases = load_cases(root / "evals")
    if not cases:
        print(f"No eval cases found under {root / 'evals'}.")
        return 1
    db = root / "memory" / "ammo.sqlite"
    if not db.is_file():
        print("No run memory yet — record runs (`ammo run`) and judge them "
              "(`ammo feedback RUN_ID good|bad`) first.")
        return 1

    with MemoryStore(db) as store:
        # exploitation only: the measurement must reflect the learned
        # preference, not the live formation's scheduled exploration nudges
        advisor = MemoryAdvisor.from_store(store, schedule_exploration=False)
        model_stats = {(r["model_id"], r["task_tag"]): r
                       for r in store.all_model_performance()}

    static_suite = EvalSuite(root=root)
    memory_suite = EvalSuite(root=root, memory=advisor)
    static_report = static_suite.run(cases)
    memory_report = memory_suite.run(cases)

    changed = []
    for s, m in zip(static_report.results, memory_report.results):
        if s.observed["team"] == m.observed["team"]:
            continue
        tag = m.observed["system"] or m.observed["domain"] or "general"
        seats = []
        before = dict(pair.split(":", 1) for pair in s.observed["team"])
        after = dict(pair.split(":", 1) for pair in m.observed["team"])
        for role in after:
            if before.get(role) != after[role]:
                seats.append({
                    "role": role,
                    "static": before.get(role),
                    "memory": after[role],
                    "why": f"{_stat_label(model_stats, after[role], tag)}; "
                           f"{_stat_label(model_stats, before.get(role), tag)}",
                })
        changed.append({"id": s.id, "tag": tag, "seats": seats})

    tags = {t for (_m, t) in model_stats}
    print("AMMO eval learning curve — static baseline vs accumulated memory")
    print(f"memory: {len(model_stats)} performance row(s) across "
          f"{len(tags)} tag(s)")
    print(f"cases fully correct: static {static_report.cases_passed}"
          f"/{len(cases)}, with memory {memory_report.cases_passed}/{len(cases)}")
    print(f"learning delta: {len(changed)}/{len(cases)} cases decided "
          "differently with memory")
    for entry in changed:
        for seat in entry["seats"]:
            print(f"  {entry['id']} ({seat['role']}): {seat['static']} -> "
                  f"{seat['memory']}  [{seat['why']}]")
    if not changed:
        print("  memory currently agrees with the static baseline everywhere "
              "— no recorded advantage yet, or the baseline is already optimal")

    now = datetime.now(timezone.utc)
    reports_dir = root / "runtime" / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    # learning-*.json: deliberately NOT eval-*.json, so `--compare`'s series
    # of same-shaped baseline reports stays clean
    path = reports_dir / f"learning-{now.strftime('%Y%m%dT%H%M%SZ')}.json"
    path.write_text(json.dumps({
        "created_at": now.isoformat(), "mode": "learning",
        "static": static_report.to_dict(), "with_memory": memory_report.to_dict(),
        "changed": changed,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"report: {path}")
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    if getattr(args, "compare", False):
        return _eval_compare(root)
    if getattr(args, "learning", False):
        return _eval_learning(root)
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
            # exploitation only (see _eval_learning): measure the learned
            # preference, not the exploration schedule
            memory = MemoryAdvisor.from_store(MemoryStore(db),
                                              schedule_exploration=False)
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
