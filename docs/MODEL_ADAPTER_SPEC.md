# Model Adapter Specification

Every model AMMO uses — Claude, Codex, local/OSS — is reached through a
**model adapter**. The adapter boundary is the single place where vendor
specifics are allowed to exist. This is what makes *"models are plugins, AMMO is
the IP"* enforceable.

> Status: **implemented** (contract + mock + command adapters). Source of truth:
> `src/ammo/adapters/`. This document describes the contract and where each
> piece lives.

## 1. Why adapters

- The kernel must never depend on a vendor SDK directly.
- Models must be swappable without touching kernel intelligence.
- Testing must be possible with mock adapters (no network, no keys).

## 2. The contract (`src/ammo/adapters/contract.py`)

```python
class BaseModelAdapter(ABC):
    def describe(self) -> dict: ...                       # static, cheap, no network
    def execute(self, request: AdapterRequest) -> AdapterResponse: ...
```

Vendor-neutral, kernel-owned types:

- `AdapterRequest` — role, model, task input, system, allowed tools, prior
  members' outputs as context.
- `AdapterResponse` — output text, declared `ToolRequest`s, `Evidence` list,
  and `Usage` (tokens; real when parsed from the provider, else a deterministic
  estimate; `cost_usd` when the provider reports real cost).
- Adapters **never self-report a confidence the kernel trusts** — trust is
  computed by the evidence-based Confidence Engine.

## 3. Secrets (constitution rule 4)

- Adapters **never** store or hard-code API keys, OAuth tokens, or secrets.
- Subscription CLIs carry their own login; AMMO only calls the command.
  API-key providers are detected by env-var *presence* (never the value).
- Mock adapters require no credentials and are the default for tests.

## 4. Implemented adapters

| Adapter | Where | Notes |
|---|---|---|
| `MockAdapter` | `adapters/mock_adapter.py` | Deterministic, offline; role-based outputs; default for tests and `run --mock`. |
| `CommandAdapter` | `adapters/command_adapter.py` | Calls an authenticated CLI (prompt via stdin); optional output parser extracts clean text + real usage. |
| `RealAdapterFactory` | `adapters/resolver.py` | Resolves each plan model to a `CommandAdapter` via detected providers; falls back to mock and records real-vs-mock. |
| Local / OSS pool | *(planned, Phase 10)* | `ollama run {model}` route exists in the catalog; unverified. |

## 5. Rules

- One adapter per model backend; adapters are small and testable.
- No adapter logic leaks above the adapter boundary; the executor receives an
  injected `model_id -> BaseModelAdapter` factory and imports no vendor.
- External effects (commands, availability probes) are injectable so the whole
  real path tests offline.

## 6. Declarative provider profile (adopted from Hermes `ProviderProfile`)

The declarative *declaration vs mechanism* split lives in
`src/ammo/providers/profile.py`: a `ProviderProfile` declares how a provider is
reached (kind, auth-check command, invoke command, usage-parser name, offered
models, cost class) while the mechanism (running commands, parsing output)
stays in `CommandAdapter` + `adapters/usage_parsers.py`. Capability-graph
fields (roles, capabilities, cost/latency/warmth) live per-model in
`registry/models.yaml`; token prices in `registry/pricing.yaml`.
See [`HERMES_INTEGRATION.md`](HERMES_INTEGRATION.md) for the adoption decision.

Caching remains an adapter-layer concern, so the kernel is free to re-form
teams above it without owning provider cache semantics.
