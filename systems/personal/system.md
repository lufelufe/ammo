# Personal — System Pack

Entry point for the Personal AI OS. Classifies a natural-language request and
routes it to personal-domain capabilities.

## Scope
- Daily / on-demand **briefings**.
- **Investment intelligence** only on explicit request (ticker, market, real estate).

## Boundaries
- Reads only within `systems/personal`; writes only to its `memory/` and `runtime/`.
- No network unless a workflow explicitly grants `web.*` tools.
- Holds no secrets. Credentials are resolved at runtime by model adapters.

## Status
Scaffold (Milestone 1): the contract is declared; behavior is not implemented.
