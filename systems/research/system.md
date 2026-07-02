# Research — System Pack

Deep-investigation domain. Surveys sources, adversarially verifies claims, and
synthesizes cited findings.

## Scope
- Literature / source scans on a topic.
- Claim verification against sources.
- Cited synthesis.

## Boundaries
- Binds **ResearchVault** (`vaults/ResearchVault`) read-write for source material.
- Network is allowed (source access) but only via granted `web.*` / `doc.read` tools.
- Holds no secrets. Credentials are resolved at runtime by model adapters.

## Status
Scaffold (Milestone 1): the contract is declared; behavior is not implemented.
