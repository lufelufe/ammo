"""Triage — self-diagnosis with proposed fixes when something goes wrong.

Two entry points:

- :func:`diagnose_exception` — an unhandled exception anywhere in the CLI is
  turned into a diagnosis card (what broke, likely causes, concrete fixes)
  instead of a raw traceback.
- :func:`diagnose_run` — after a run, failure *signals* (failed invocations,
  denied tools, unpriced models, everything-estimated usage in real mode) are
  collected into actionable diagnoses.

Rule-based and offline: no model call, no secrets. Unknown errors still get a
generic card plus the traceback tail, so nothing is swallowed silently.
"""

from __future__ import annotations

import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Diagnosis:
    problem: str
    causes: List[str] = field(default_factory=list)
    fixes: List[str] = field(default_factory=list)

    def to_text(self) -> str:
        lines = [f"self-diagnosis: {self.problem}"]
        lines += [f"  likely cause: {c}" for c in self.causes]
        lines += [f"  try: {f}" for f in self.fixes]
        return "\n".join(lines)


# -- exception triage -----------------------------------------------------------

def diagnose_exception(exc: BaseException) -> Diagnosis:
    name = type(exc).__name__
    # match on the whole MRO so subclasses hit their family's rule
    # (e.g. ValidationError(RegistryError), sqlite3.OperationalError(DatabaseError))
    family = {c.__name__ for c in type(exc).__mro__}
    text = str(exc)

    if name == "ModuleNotFoundError":
        return Diagnosis(
            f"a required package is missing ({text})",
            ["running with the system Python instead of the project venv"],
            ["source .venv/bin/activate  (or use .venv/bin/python -m ammo ...)",
             'pip install -e ".[dev]" inside the venv'],
        )
    if family & {"YAMLError", "ParserError", "ScannerError", "ComposerError"}:
        return Diagnosis(
            "a YAML file failed to parse",
            ["a hand-edited registry/spec file has a syntax error (the message "
             "above names the file and line)"],
            ["fix the reported line, or restore the file from git (`git checkout -- <file>`)",
             "ammo doctor -v  (structural check)"],
        )
    if name == "JSONDecodeError":
        return Diagnosis(
            "a JSON file/output failed to parse",
            ["a corrupted run artifact under runtime/runs/, or unexpected CLI output"],
            ["delete the broken run directory (history only), or re-run the command",
             "ammo dream --apply  (prunes stale run artifacts)"],
        )
    if family & {"DatabaseError", "OperationalError", "IntegrityError"}:
        return Diagnosis(
            "the memory database errored",
            ["memory/ammo.sqlite is corrupted or locked by another process"],
            ["restore the dream backup: cp memory/ammo.sqlite.bak memory/ammo.sqlite",
             "or move the db aside to start fresh (aggregates rebuild over time)"],
        )
    if "RegistryError" in family:
        return Diagnosis(
            f"a registry/pack failed validation ({text.splitlines()[0] if text else name})",
            ["a registry file or system pack breaks the contract (a wrapped "
             "YAML syntax error names the file and line above)"],
            ["fix the reported line, or restore from git (`git checkout -- <file>`)",
             "ammo doctor -v",
             "ammo adopt <system>  (fills missing pack files non-destructively)"],
        )
    if name == "FileNotFoundError":
        return Diagnosis(
            f"a required path is missing ({text})",
            ["wrong AMMO root (AMMO_ROOT env or cwd), or a mounted source moved"],
            ["ammo doctor", "echo $AMMO_ROOT  (unset it to use the repo root)"],
        )
    if name == "PermissionError":
        return Diagnosis(
            f"the filesystem refused access ({text})",
            ["the AMMO root or a mounted directory is not writable by this user"],
            ["check ownership/permissions of the reported path", "ammo doctor -v"],
        )
    tail = traceback.format_exception_only(type(exc), exc)[-1].strip()
    return Diagnosis(
        f"unexpected error: {tail}",
        ["this path has no triage rule yet"],
        ["re-run with the same input to check it reproduces",
         "ammo doctor -v",
         "report it — and add a triage rule for it in src/ammo/triage.py"],
    )


# -- run-signal triage ------------------------------------------------------------

def diagnose_run(responses, economics: Optional[Dict[str, Any]] = None,
                 system_id: Optional[str] = None, mode: str = "mock") -> List[Diagnosis]:
    out: List[Diagnosis] = []

    failed_invocations = [
        (r.role, r.model) for r in responses
        if any(ev.kind == "invocation" and not ev.ok for ev in r.evidence)
    ]
    if failed_invocations:
        who = ", ".join(f"{role}({model})" for role, model in failed_invocations)
        out.append(Diagnosis(
            f"member invocation kept failing after retry: {who}",
            ["the provider CLI is not authenticated, rate-limited, or its "
             "output format changed"],
            ["ammo providers  (auth status per provider)",
             "claude auth status / codex login status",
             "re-run; if it persists, run with --mock to isolate AMMO from the provider"],
        ))

    denied = [ev.summary for r in responses for ev in r.evidence
              if ev.kind == "tool" and not ev.ok]
    if denied:
        where = f"systems/{system_id}/.ammo/permissions.yaml" if system_id else "the pack's permissions.yaml"
        out.append(Diagnosis(
            f"tool(s) denied by the permission gate: {', '.join(sorted(set(denied))[:3])}",
            [f"the tool is not in tools.allow (or the path is excluded) in {where}"],
            [f"allow it in {where} if intended, or re-plan without it",
             "check .ammoignore if a specific path was blocked"],
        ))

    if economics and economics.get("unpriced_models"):
        models = ", ".join(economics["unpriced_models"])
        out.append(Diagnosis(
            f"unpriced model(s) in the cost report: {models}",
            ["registry/pricing.yaml has no entry for them"],
            [f"ammo pricing set <model> <in> <out>  (for: {models})"],
        ))

    if mode == "real" and responses:
        real_usages = [r.usage for r in responses if r.usage is not None]
        if real_usages and all(u.estimated for u in real_usages):
            out.append(Diagnosis(
                "every member's usage is an estimate even though the run was real",
                ["the provider CLI's structured output changed shape, so the "
                 "usage parser fell back"],
                ["check `claude --version` / `codex --version` against the "
                 "verified versions in src/ammo/providers/profile.py",
                 "inspect one raw output and update src/ammo/adapters/usage_parsers.py"],
            ))
    return out
