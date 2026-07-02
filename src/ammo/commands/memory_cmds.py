"""ammo CLI handlers — memory cmds (split from cli.py)."""

import argparse
import sys
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root


def _cmd_memory_help(_args: argparse.Namespace) -> int:
    print("Usage: ammo memory <stats|runs>")
    return 0


def _cmd_memory_stats(_args: argparse.Namespace) -> int:
    with MemoryStore.open(find_ammo_root()) as memory:
        stats = memory.stats()
    print(f"AMMO memory — runs: {stats['total_runs']}")
    if not stats["total_runs"]:
        print("(no runs recorded yet)")
        return 0
    print("by domain: " + ", ".join(f"{d}={n}" for d, n in stats["by_domain"].items()))
    print("models (by attempts):")
    for m in stats["models"]:
        rate = (m["successes"] / m["attempts"]) if m["attempts"] else 0.0
        print(
            f"  - {m['model_id']} [{m['task_tag']}]  attempts {m['attempts']}  "
            f"success {m['successes']} ({rate:.0%})  avg_conf {m['average_confidence']}"
        )
    print("teams (by attempts):")
    for t in stats["teams"]:
        print(
            f"  - {t['team_signature']} [{t['task_tag']}]  attempts {t['attempts']}  "
            f"success {t['successes']}  avg_conf {t['average_confidence']}"
        )
    return 0


def _cmd_memory_runs(args: argparse.Namespace) -> int:
    with MemoryStore.open(find_ammo_root()) as memory:
        runs = memory.list_runs(limit=args.limit)
    if not runs:
        print("(no runs recorded yet)")
        return 0
    print("recent runs:")
    for r in runs:
        print(
            f"  - {r['run_id']}  {r['timestamp']}  domain={r['domain']}  "
            f"system={r['selected_system']}  models={r['selected_models']}  "
            f"conf={r['confidence_score']}  outcome={r['outcome_status']}"
        )
    return 0


def _cmd_feedback(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    db = root / "memory" / "ammo.sqlite"
    if not db.is_file():
        print("No run memory yet.", file=sys.stderr)
        return 1
    with MemoryStore(db) as memory:
        try:
            result = memory.apply_feedback(args.run_id, args.verdict == "good", args.note)
        except KeyError as exc:
            print(f"feedback: {exc}", file=sys.stderr)
            return 1
    print(f"recorded: {result['run_id']} -> {result['feedback']}")
    if result["corrected"] > 0:
        print("improvement loop corrected: the confidence proxy had under-credited this team (+1 success)")
    elif result["corrected"] < 0:
        print("improvement loop corrected: the confidence proxy had over-credited this team (-1 success)")
    return 0


_CAL_BANDS = (("very_low", 0.0, 0.25), ("low", 0.25, 0.5),
              ("medium", 0.5, 0.75), ("high", 0.75, 1.01))


def _cmd_calibrate(_args: argparse.Namespace) -> int:
    root = find_ammo_root()
    db = root / "memory" / "ammo.sqlite"
    rows = []
    if db.is_file():
        with MemoryStore(db) as memory:
            rows = memory.feedback_rows()
    if not rows:
        print("No feedback recorded yet — after a run, judge it with "
              "`ammo feedback <run_id> good|bad`. Calibration needs that ground truth.")
        return 0

    print(f"Calibration — {len(rows)} judged run(s). A well-calibrated band's "
          "good-rate should sit inside its score range:")
    for band, lo, hi in _CAL_BANDS:
        in_band = [r for r in rows if r["confidence_score"] is not None
                   and lo <= r["confidence_score"] < hi]
        if not in_band:
            continue
        good = sum(1 for r in in_band if str(r["user_feedback"]).startswith("good"))
        rate = good / len(in_band)
        marker = ""
        if rate < lo:
            marker = "  <- OVERCONFIDENT (good-rate below the band)"
        elif rate >= hi:
            marker = "  <- underconfident (good-rate above the band)"
        print(f"  {band:9} n={len(in_band):<3} good-rate={rate:.0%}{marker}")
    if len(rows) < 10:
        print(f"note: only {len(rows)} sample(s) — collect ~10+ before adjusting weights.")
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    from ammo.dream import DreamEngine

    engine = DreamEngine(find_ammo_root(), window=args.window,
                         journal_keep=args.journal_keep)
    report = engine.apply() if args.apply else engine.plan()
    print(report.to_text())
    return 0
