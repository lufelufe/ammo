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


def _cmd_calibrate(args: argparse.Namespace) -> int:
    from ammo.kernel.confidence import calibrate

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

    result = calibrate(rows)
    print(f"Calibration — {result.samples} judged run(s). A well-calibrated "
          "band's good-rate should sit inside its score range:")
    for stat in result.bands:
        marker = ""
        if stat.verdict == "overconfident":
            marker = "  <- OVERCONFIDENT (good-rate below the band)"
        elif stat.verdict == "underconfident":
            marker = "  <- underconfident (good-rate above the band)"
        print(f"  {stat.band:9} n={stat.n:<3} good-rate={stat.good_rate:.0%}{marker}")

    if result.suggested_offset is None:
        print(f"note: only {result.samples} sample(s) — collect ~10+ before "
              "adjusting weights.")
        if getattr(args, "apply", False):
            print("--apply refused: not enough judged runs for a correction.")
            return 1
        return 0

    from ammo.config import AmmoConfig, load_config, save_config

    config = load_config(root) or AmmoConfig()
    print(f"suggested correction: {result.suggested_offset:+.2f} "
          f"(currently applied: {config.confidence_offset:+.2f})")
    if not getattr(args, "apply", False):
        if result.suggested_offset != config.confidence_offset:
            print("apply it with `ammo calibrate --apply` — future runs' "
                  "confidence shifts toward your verdicts.")
        return 0
    config.confidence_offset = result.suggested_offset
    save_config(root, config)
    print(f"applied: confidence_offset={result.suggested_offset:+.2f} "
          "(ammo.config.yaml; the engine now corrects future scores)")
    return 0


def _cmd_dream(args: argparse.Namespace) -> int:
    from ammo.dream import DreamEngine

    engine = DreamEngine(find_ammo_root(), window=args.window,
                         journal_keep=args.journal_keep)
    report = engine.apply() if args.apply else engine.plan()
    print(report.to_text())
    return 0
