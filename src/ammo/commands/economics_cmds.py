"""ammo CLI handlers — economics cmds (split from cli.py)."""

import argparse
from ammo.memory import MemoryAdvisor, MemoryStore, team_signature
from ammo.paths import find_ammo_root


def _cmd_pricing_show(_args: argparse.Namespace) -> int:
    from ammo.economics import PricingBook

    book = PricingBook.load(find_ammo_root())
    if not book.prices:
        print("No pricing book found (registry/pricing.yaml).")
        return 0
    print(f"Pricing ({book.currency}/MTok, as of {book.as_of or 'unknown'}):")
    for price in sorted(book.prices.values(), key=lambda p: p.id):
        print(f"  - {price.id:22} in ${price.price_per_mtok_in:<7g} "
              f"out ${price.price_per_mtok_out:<7g} [{price.billing}] ({price.source})")
    return 0


def _cmd_pricing_set(args: argparse.Namespace) -> int:
    from ammo.economics import PricingBook

    book = PricingBook.load(find_ammo_root())
    price = book.set_price(args.model_id, args.price_in, args.price_out,
                           billing=args.billing)
    book.save()
    print(f"Updated {price.id}: in ${price.price_per_mtok_in}/MTok, "
          f"out ${price.price_per_mtok_out}/MTok [{price.billing}]")
    return 0


def _cmd_efficiency(args: argparse.Namespace) -> int:
    root = find_ammo_root()
    if not (root / "memory" / "ammo.sqlite").is_file():
        print("No run memory yet — run some tasks first (`ammo run --mock ...`).")
        return 0

    with MemoryStore.open(root) as memory:
        models = memory.all_model_performance()
        teams = memory.all_team_synergy()

    if args.system:
        models = [m for m in models if m["task_tag"] == args.system]
        teams = [t for t in teams if t["task_tag"] == args.system]
    if not models:
        print("No recorded performance for that scope.")
        return 0

    def model_efficiency(m):
        cost = m.get("average_cost") or 0.0
        conf = m.get("average_confidence") or 0.0
        return conf / cost if cost > 0 else float("inf") if conf > 0 else 0.0

    print("Model efficiency (quality per $; local/subscription-covered = inf):")
    for m in sorted(models, key=lambda m: (m["task_tag"], -model_efficiency(m))):
        eff = model_efficiency(m)
        eff_str = "inf" if eff == float("inf") else f"{eff:.0f}"
        print(f"  [{m['task_tag']}] {m['model_id']:22} conf {m['average_confidence']:<5} "
              f"tokens {m.get('average_tokens') or 0:<7} cost ${m.get('average_cost') or 0:.4f} "
              f" eff {eff_str}")

    # exploration convergence per tag (deterministic epsilon schedule)
    from ammo.memory import MemoryAdvisor

    with MemoryStore(root / "memory" / "ammo.sqlite") as memory:
        advisor = MemoryAdvisor.from_store(memory)
    tags = sorted({m["task_tag"] for m in models})
    if tags:
        print("Exploration (annealed epsilon):")
        for tag in tags:
            active, epsilon, n = advisor.exploration_state(tag)
            period = max(1, round(1 / epsilon))
            status = "explore NOW" if active else f"next at attempt ~{((n // period) + 1) * period + period - 1}"
            print(f"  [{tag}] ε={epsilon:.3f}  attempts={n}  {status}")

    if teams:
        print("Team combinations:")
        for t in sorted(teams, key=lambda t: (t["task_tag"], -(t["average_confidence"] or 0))):
            print(f"  [{t['task_tag']}] {t['team_signature']}")
            print(f"      attempts {t['attempts']}  success {t['successes']}  "
                  f"conf {t['average_confidence']}  cost ${t.get('average_cost') or 0:.4f}")
    return 0
