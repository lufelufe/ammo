"""Resolve a model id to a real adapter (or a mock fallback).

Given detected provider availability, map each model to a `CommandAdapter` that
calls the authenticated CLI. Models with no available command-capable provider
fall back to `MockAdapter` (recorded, so the caller can report real-vs-mock).
AMMO stores no secrets; the CLI carries its own auth.
"""

from __future__ import annotations

from typing import Callable, Dict, List, Optional, Tuple

from ammo.adapters.command_adapter import CommandAdapter
from ammo.adapters.contract import BaseModelAdapter
from ammo.adapters.mock_adapter import MockAdapter

Runner = Callable[..., Tuple[int, str]]


def _invoke_command(profile, model_id: str) -> Optional[List[str]]:
    if not profile.invoke:
        return None
    command = [token.replace("{model}", model_id) for token in profile.invoke]
    # per-model extra args (e.g. `--model haiku` on the shared claude CLI)
    command += list(getattr(profile, "model_args", {}).get(model_id, []))
    return command


class RealAdapterFactory:
    """Callable ``model_id -> BaseModelAdapter`` for real execution."""

    def __init__(self, root=None, statuses=None, runner: Optional[Runner] = None,
                 allow_paid: bool = False, transport=None):
        from ammo.providers import DEFAULT_CATALOG, AvailabilityDetector, select_models

        self._runner = runner
        self._transport = transport  # injectable HTTP transport (offline tests)
        self.statuses = (
            statuses if statuses is not None
            else AvailabilityDetector().detect_all(DEFAULT_CATALOG)
        )
        self.usable = select_models(self.statuses, allow_paid=allow_paid)
        self._profiles = {s.profile.id: s.profile for s in self.statuses}
        self.resolutions: Dict[str, Tuple[str, Optional[str]]] = {}

    def __call__(self, model_id: str) -> BaseModelAdapter:
        provider_id = self.usable.get(model_id)
        profile = self._profiles.get(provider_id) if provider_id else None
        command = _invoke_command(profile, model_id) if profile else None
        if provider_id and command:
            from ammo.adapters.usage_parsers import PARSERS

            self.resolutions[model_id] = ("real", provider_id)
            return CommandAdapter(model_id, command, self._runner,
                                  parser=PARSERS.get(profile.parser))
        if profile is not None and profile.api_url:
            from ammo.adapters.http_adapter import HttpAdapter

            # paid API route (only reachable when allow_paid selected it and
            # the env var is present); the key itself is read at call time
            self.resolutions[model_id] = ("real", provider_id)
            return HttpAdapter(model_id, profile, transport=self._transport)
        # unavailable -> mock
        self.resolutions[model_id] = ("mock", provider_id)
        return MockAdapter(model_id)

    @property
    def real_count(self) -> int:
        return sum(1 for kind, _ in self.resolutions.values() if kind == "real")
