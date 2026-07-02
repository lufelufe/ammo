"""Detect which providers (and therefore models) are actually available.

Everything external is injectable (`which`, `run`, `environ`) so this is fully
testable without real CLIs or network. AMMO only calls commands and reads env
var *presence* — it never stores or prints secret values.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from typing import Callable, Dict, List, Optional, Tuple

from ammo.providers.profile import (
    API,
    LOCAL,
    SUBSCRIPTION_CLI,
    ProviderProfile,
    ProviderStatus,
)

# runner(cmd, stdin) -> (exit_code, stdout)
Runner = Callable[..., Tuple[int, str]]


def expand_env(overrides: dict) -> dict:
    """os.environ + provider overrides (values get ~ and $VAR expansion)."""
    import os

    merged = dict(os.environ)
    for key, value in (overrides or {}).items():
        merged[key] = os.path.expandvars(os.path.expanduser(str(value)))
    return merged


def default_runner(cmd: List[str], stdin: str = "", timeout: int = 180,
                   env: dict = None) -> Tuple[int, str]:
    # 180s default: verified real invocations (claude -p) can take ~20s on a
    # trivial prompt and much longer on real work; probes return in <1s anyway.
    try:
        proc = subprocess.run(
            cmd, input=stdin, capture_output=True, text=True, timeout=timeout,
            env=env,
        )
        return proc.returncode, proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return 127, ""


def _parse_local_models(output: str) -> List[str]:
    models = []
    for line in output.splitlines():
        line = line.strip()
        if not line or line.upper().startswith("NAME"):  # skip header
            continue
        models.append(line.split()[0])
    return models


class AvailabilityDetector:
    def __init__(
        self,
        runner: Optional[Runner] = None,
        which: Optional[Callable[[str], Optional[str]]] = None,
        environ: Optional[Dict[str, str]] = None,
    ):
        self._run = runner or default_runner
        self._which = which or shutil.which
        self._env = environ if environ is not None else os.environ

    def detect(self, profile: ProviderProfile) -> ProviderStatus:
        if profile.kind == SUBSCRIPTION_CLI:
            return self._detect_cli(profile)
        if profile.kind == LOCAL:
            return self._detect_local(profile)
        if profile.kind == API:
            return self._detect_api(profile)
        return ProviderStatus(profile, False, f"unknown kind '{profile.kind}'", [])

    def detect_all(self, catalog: List[ProviderProfile]) -> List[ProviderStatus]:
        return [self.detect(p) for p in catalog]

    # -- per-kind ----------------------------------------------------------

    def _detect_cli(self, profile: ProviderProfile) -> ProviderStatus:
        if not self._which(profile.command):
            return ProviderStatus(profile, False, "not installed", [])
        if profile.auth_check:
            if profile.env:
                code, out = self._run(profile.auth_check, env=expand_env(profile.env))
            else:
                code, out = self._run(profile.auth_check)
            # exit code alone is not proof: `claude auth status` exits 0 even
            # when logged out (verified live) — require the expected marker too
            authed = code == 0 and (
                profile.auth_expect is None or profile.auth_expect in (out or "")
            )
            if not authed:
                return ProviderStatus(profile, False, "installed but not authenticated", [])
            return ProviderStatus(profile, True, "authenticated", list(profile.models))
        return ProviderStatus(profile, True, "installed", list(profile.models))

    def _detect_local(self, profile: ProviderProfile) -> ProviderStatus:
        if not self._which(profile.command):
            return ProviderStatus(profile, False, "not installed", [])
        if profile.list_command:
            code, out = self._run(profile.list_command)
            models = _parse_local_models(out) if code == 0 else []
            detail = f"{len(models)} local model(s)" if models else "no local models"
            return ProviderStatus(profile, bool(models), detail, models)
        return ProviderStatus(profile, True, "installed", list(profile.models))

    def _detect_api(self, profile: ProviderProfile) -> ProviderStatus:
        # presence only — never read or print the secret value.
        if self._env.get(profile.env_var):
            return ProviderStatus(profile, True, f"API key configured ({profile.env_var})", list(profile.models))
        return ProviderStatus(profile, False, f"no API key ({profile.env_var} unset)", [])


def select_models(
    statuses: List[ProviderStatus], *, allow_paid: bool = False
) -> Dict[str, str]:
    """Map available model_id -> provider id, preferring no-extra-cost providers.

    With a subscription/local route available for a model, the paid API route is
    skipped unless ``allow_paid=True`` (enforces 'don't spend API money when a
    subscription already covers it').
    """
    chosen: Dict[str, str] = {}
    for status in statuses:
        if not status.available:
            continue
        if status.profile.cost == "paid" and not allow_paid:
            continue
        for model_id in status.models:
            chosen.setdefault(model_id, status.profile.id)  # first (included) wins
    return chosen
