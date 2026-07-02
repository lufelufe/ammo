"""ammo CLI handlers — summon (split from cli.py)."""

import argparse
from ammo.paths import find_ammo_root


def _cmd_start(args: argparse.Namespace) -> int:
    from ammo.bootstrap import run_start

    return run_start(
        find_ammo_root(), args.host,
        reconfigure=args.reconfigure, assume_yes=args.yes,
    )


def _cmd_status(_args: argparse.Namespace) -> int:
    from ammo.bootstrap import build_status

    print(build_status(find_ammo_root()))
    return 0
