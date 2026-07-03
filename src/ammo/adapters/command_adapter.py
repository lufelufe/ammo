"""CommandAdapter — reach a real model by calling an authenticated CLI.

AMMO only calls the command; the CLI is logged in with its own account, and AMMO
stores no keys or tokens. The command is injectable so this is testable without
a real provider. It does NOT self-report confidence — trust is computed by the
evidence-based Confidence Engine, never claimed by the model.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, List, Optional, Tuple

from ammo.adapters.contract import AdapterRequest, AdapterResponse, BaseModelAdapter, Usage

Runner = Callable[..., Tuple[int, str]]


def _build_prompt(request: AdapterRequest) -> str:
    lines = [f"[role] {request.role}", f"[task] {request.task_input}"]
    if request.system:
        lines.append(f"[system] {request.system}")
    if request.context:
        prior = "; ".join(f"{r}: {o}" for r, o in request.context.items())
        lines.append(f"[context] {prior}")
    return "\n".join(lines)


class CommandAdapter(BaseModelAdapter):
    def __init__(self, model_id: str, command: List[str], runner: Optional[Runner] = None,
                 parser=None, env: dict = None):
        super().__init__(model_id)
        self._command = list(command)
        self._parser = parser  # optional (stdout) -> (clean_text, Usage|None)
        self._env = env or {}  # provider env overrides (e.g. a second account's
                               # CLAUDE_CONFIG_DIR) — paths only, never secrets
        if runner is not None:
            self._run = runner
        else:
            from ammo.providers.detector import default_runner

            self._run = default_runner

    def describe(self) -> Dict[str, Any]:
        return {
            "id": self.model_id,
            "kind": "command",
            "command": self._command[0] if self._command else None,
        }

    def execute(self, request: AdapterRequest) -> AdapterResponse:
        import time

        prompt = _build_prompt(request)
        started = time.perf_counter()
        if self._env:
            from ammo.providers.detector import expand_env

            code, output = self._run(self._command, stdin=prompt,
                                     env=expand_env(self._env))
        else:
            code, output = self._run(self._command, stdin=prompt)
        latency_ms = round((time.perf_counter() - started) * 1000, 1)
        text = output.strip()
        if code != 0:
            text = text or f"(command exited {code})"

        usage = None
        if self._parser is not None and code == 0:
            text, usage = self._parser(output)
            text = text.strip()

        if usage is None:  # no parser, or the output didn't match — estimate
            from ammo.adapters.mock_adapter import estimate_tokens

            usage = Usage(
                input_tokens=estimate_tokens(prompt),
                output_tokens=estimate_tokens(text),
                estimated=True,
            )

        usage.latency_ms = latency_ms   # real wall-clock, whichever usage path

        return AdapterResponse(
            role=request.role,
            model=request.model,
            output=text,
            confidence=0.0,        # evidence-based confidence is computed elsewhere
            reasoning=f"command:{self._command[0] if self._command else '?'}",
            usage=usage,
        )
