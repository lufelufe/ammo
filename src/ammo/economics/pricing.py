"""PricingBook — estimate cost from token usage, however the model is reached.

Policy: cost is always estimated from tokens. `api` billing is real spend,
`subscription` is an equivalent-value estimate (covered by the plan), `local`
is compute-only (priced 0 in v0). Prices live in ``registry/pricing.yaml`` and
can be updated by hand, via ``ammo pricing set``, or through a pluggable
:class:`PriceSource` (e.g. a future web-search module). No secrets.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol

PRICING_FILE = "pricing.yaml"
_MTOK = 1_000_000


@dataclass
class ModelPrice:
    id: str
    billing: str = "local"            # api | subscription | local
    price_per_mtok_in: float = 0.0
    price_per_mtok_out: float = 0.0
    source: str = "estimate"

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        return (
            input_tokens * self.price_per_mtok_in
            + output_tokens * self.price_per_mtok_out
        ) / _MTOK


class PriceSource(Protocol):
    """Hook for an external price provider (e.g. a web-search module)."""

    def lookup(self, model_id: str) -> Optional[ModelPrice]:
        ...


class PricingBook:
    def __init__(self, prices: Dict[str, ModelPrice], path: Optional[Path] = None,
                 currency: str = "USD", as_of: str = ""):
        self.prices = prices
        self.path = path
        self.currency = currency
        self.as_of = as_of

    @classmethod
    def load(cls, root: Path) -> "PricingBook":
        import yaml

        path = Path(root) / "registry" / PRICING_FILE
        if not path.is_file():
            return cls({}, path=path)
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        prices = {}
        for entry in data.get("models", []) or []:
            # A family entry (`engines: [claude_a, claude_b]`) prices every
            # composed node `{engine}_{id}` identically — the price is a
            # property of the MODEL, not of the account serving it. Mirrors
            # registry/models.yaml expansion (registry/loaders.py).
            engines = entry.get("engines") or []
            node_ids = [f"{engine}_{entry['id']}" for engine in engines] or [entry["id"]]
            for node_id in node_ids:
                prices[node_id] = ModelPrice(
                    id=node_id,
                    billing=entry.get("billing", "local"),
                    price_per_mtok_in=float(entry.get("price_per_mtok_in") or 0),
                    price_per_mtok_out=float(entry.get("price_per_mtok_out") or 0),
                    source=entry.get("source", "estimate"),
                )
        return cls(prices, path=path, currency=data.get("currency", "USD"),
                   as_of=str(data.get("as_of", "")))

    def get(self, model_id: str) -> Optional[ModelPrice]:
        return self.prices.get(model_id)

    def set_price(self, model_id: str, price_in: float, price_out: float,
                  billing: Optional[str] = None, source: str = "manual") -> ModelPrice:
        existing = self.prices.get(model_id)
        price = ModelPrice(
            id=model_id,
            billing=billing or (existing.billing if existing else "api"),
            price_per_mtok_in=price_in,
            price_per_mtok_out=price_out,
            source=source,
        )
        self.prices[model_id] = price
        return price

    def refresh(self, source: PriceSource, model_ids: List[str]) -> List[str]:
        """Pull prices for the given models from an external PriceSource."""
        updated = []
        for model_id in model_ids:
            price = source.lookup(model_id)
            if price is not None:
                self.prices[model_id] = price
                updated.append(model_id)
        return updated

    def save(self) -> Path:
        import yaml

        if self.path is None:
            raise ValueError("PricingBook has no backing path")
        data = {
            "apiVersion": "ammo/v1",
            "kind": "PricingBook",
            "currency": self.currency,
            "as_of": self.as_of,
            "models": [
                {
                    "id": p.id,
                    "billing": p.billing,
                    "price_per_mtok_in": p.price_per_mtok_in,
                    "price_per_mtok_out": p.price_per_mtok_out,
                    "source": p.source,
                }
                for p in self.prices.values()
            ],
        }
        header = "# PricingBook — managed by `ammo pricing`. No secrets.\n"
        self.path.write_text(header + yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
        return self.path

    # -- run economics --------------------------------------------------------

    def run_economics(self, responses) -> Dict[str, Any]:
        """Aggregate tokens and estimated cost for a run's adapter responses."""
        by_model: Dict[str, Dict[str, Any]] = {}
        for response in responses:
            usage = getattr(response, "usage", None)
            tokens_in = usage.input_tokens if usage else 0
            tokens_out = usage.output_tokens if usage else 0
            price = self.get(response.model)
            reported = getattr(usage, "cost_usd", None) if usage else None
            if reported is not None:
                cost = float(reported)   # provider-reported real cost wins
            else:
                cost = price.cost(tokens_in, tokens_out) if price else 0.0
            latency = getattr(usage, "latency_ms", None) if usage else None
            bucket = by_model.setdefault(response.model, {
                "model": response.model,
                "billing": price.billing if price else "unknown",
                "priced": price is not None or reported is not None,
                "input_tokens": 0, "output_tokens": 0, "cost": 0.0,
                "latency_ms": 0.0, "_latency_n": 0,
            })
            bucket["input_tokens"] += tokens_in
            bucket["output_tokens"] += tokens_out
            bucket["cost"] += cost
            if latency is not None:
                bucket["latency_ms"] += float(latency)
                bucket["_latency_n"] += 1

        models = list(by_model.values())
        for m in models:
            m["cost"] = round(m["cost"], 6)
            n = m.pop("_latency_n", 0)
            m["latency_ms"] = round(m["latency_ms"] / n, 1) if n else None
        total_in = sum(m["input_tokens"] for m in models)
        total_out = sum(m["output_tokens"] for m in models)
        return {
            "currency": self.currency,
            "model_count": len(models),
            "total_input_tokens": total_in,
            "total_output_tokens": total_out,
            "total_tokens": total_in + total_out,
            "estimated_cost": round(sum(m["cost"] for m in models), 6),
            "unpriced_models": sorted(m["model"] for m in models if not m["priced"]),
            "by_model": sorted(models, key=lambda m: m["model"]),
        }
