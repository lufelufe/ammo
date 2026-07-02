"""Economics — token usage and cost estimation for AMMO runs.

Cost is always estimated from token usage: `api` = real spend, `subscription` =
equivalent value (covered by the plan), `local` = compute-only (0 in v0). The
data feeds the improvement loop so team formation can optimize for performance,
cost, or speed.
"""

from ammo.economics.pricing import ModelPrice, PriceSource, PricingBook

__all__ = ["PricingBook", "ModelPrice", "PriceSource"]
