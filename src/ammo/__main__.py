"""Enable ``python -m ammo``.

Delegates to the CLI entry point so ``python -m ammo --help`` works.
"""

from ammo.cli import main

if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
