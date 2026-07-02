"""Team templates and position specs for Dynamic Team Formation v0.

Pure data. A *template* is an ordered list of team positions. A *position* is
resolved to a concrete model either by scoring the capability graph
(POSITION_SPEC) or by a fixed infrastructure id (FIXED_MODELS, e.g. a test
runner is a harness, not an LLM).
"""

from __future__ import annotations

# position -> (capability, role) used to score the capability graph.
POSITION_SPEC = {
    "fast_worker": {"capability": "general", "role": None},
    "planner": {"capability": "planning", "role": "analyst"},
    "builder": {"capability": "coding", "role": "implementer"},
    "critic": {"capability": "review", "role": "critic"},
    "researcher": {"capability": "analysis", "role": "analyst"},
    "skeptic": {"capability": "review", "role": "critic"},
    "synthesizer": {"capability": "general", "role": "synthesizer"},
    "judge": {"capability": "review", "role": "critic"},
    "triage": {"capability": "analysis", "role": "analyst"},
    "operator": {"capability": "coding", "role": "implementer"},
    "rollback_critic": {"capability": "review", "role": "critic"},
    # registry-role names, so pack workflows.yaml stages resolve as positions
    "analyst": {"capability": "analysis", "role": "analyst"},
    "implementer": {"capability": "coding", "role": "implementer"},
    "reviewer": {"capability": "review", "role": "reviewer"},
}

# positions that are infrastructure, not LLMs — resolved to a fixed id.
FIXED_MODELS = {
    "test_runner": "local_test_runner",
}

TEMPLATES = {
    "simple_fast": ["fast_worker"],
    "research": ["researcher", "skeptic", "synthesizer"],
    "investment_research": ["researcher", "critic", "judge"],
    "coding_high_risk": ["planner", "builder", "critic", "test_runner"],
    "coding_standard": ["builder", "critic"],
    "ops_incident": ["triage", "operator", "rollback_critic"],
    "generalist": ["planner", "synthesizer"],
}

# always applied (constitution rule 4: teams never get secret access).
BASE_RISK_CONTROLS = ["no_secret_access"]

TEMPLATE_RISK_CONTROLS = {
    "coding_high_risk": ["require_tests", "diff_review"],
    "coding_standard": ["diff_review"],
    "ops_incident": ["dry_run_first", "rollback_plan"],
    "investment_research": ["cite_sources", "no_financial_advice"],
    "research": ["cite_sources", "adversarial_check"],
    "simple_fast": [],
    "generalist": [],
}

TEMPLATE_TOOLS = {
    "coding_high_risk": ["fs.read", "fs.write", "git", "shell.run"],
    "coding_standard": ["fs.read", "fs.write", "git"],
    "ops_incident": ["shell.run"],
    "investment_research": ["web.search", "web.fetch", "doc.read"],
    "research": ["web.search", "web.fetch", "doc.read"],
    "simple_fast": [],
    "generalist": [],
}

# templates with a bespoke expected-output set (others derive from the task).
TEMPLATE_OUTPUTS = {
    "research": ["report", "citations"],
    "investment_research": ["research_brief", "citations", "verdict"],
    "ops_incident": ["incident_report", "remediation_actions"],
}

TOOL_ORDER = ["web.search", "web.fetch", "doc.read", "fs.read", "fs.write", "shell.run", "git", "cron"]
