"""Dynamic Team Formation (v0).

Turns a TaskVector + CapabilityGraph into an ExecutionPlan — a temporary team of
(role, model) members with tools, risk controls, and expected outputs. This is
what makes AMMO a team-formation engine rather than a router. Nothing is executed.
"""

from ammo.kernel.team_formation.execution_plan import ExecutionPlan, TeamMember
from ammo.kernel.team_formation.former import TeamFormer, form_team

__all__ = ["ExecutionPlan", "TeamMember", "TeamFormer", "form_team"]
