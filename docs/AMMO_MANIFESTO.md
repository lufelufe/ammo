# AMMO Manifesto

> **AMMO is not a router. AMMO is the adaptive orchestration kernel of a Personal AI OS.**

## 1. What AMMO is

AMMO (Adaptive Multi-Model Orchestrator) is the **kernel** of a Personal AI
Operating System. It is not a program that calls a model. It is a system that:

- **Understands** a problem before acting on it.
- **Composes** a temporary, purpose-built AI team for that problem.
- **Executes** — first as a mock, later for real — through model adapters.
- **Scores** the confidence of every result.
- **Remembers** what worked and what failed, and lets that memory change how
  the *next* team is formed.

AMMO learns. A router does not.

## 2. What AMMO is not

- Not a model. Models come and go.
- Not a router. A router maps a request to one endpoint and stops.
- Not a prompt library. Prompts are inputs, not the kernel.
- Not tied to any single vendor. Claude, Codex, and local/OSS models are
  **plugins**.

## 3. The core inversion

> **Models are plugins. AMMO is the IP.**

The value does not live in any model. It lives in the kernel's ability to
understand tasks, form teams, judge confidence, and learn. Any individual
model must be replaceable without touching the kernel's intelligence.

## 4. The kernel loop

```
structure → register → analyze → form team → mock execution
          → confidence → memory → connect real models
```

Restated:

1. **Structure** — a clean, stable substrate (system packs, registries).
2. **Register** — declare available capabilities and models.
3. **Analyze** — understand the incoming task.
4. **Form team** — dynamically assemble the right capabilities/models.
5. **Mock execution** — simulate before spending real calls.
6. **Confidence** — quantify how much to trust the result.
7. **Memory** — record outcomes; feed them back into future team formation.
8. **Connect real models** — bind adapters to real providers, last.

## 5. Constitutional rules

1. Work only on the current milestone.
2. Do not implement future milestones unless explicitly asked.
3. Preserve the architecture: models are plugins, AMMO is the IP.
4. Never store API keys, OAuth tokens, secrets, or credentials in the repo.
5. Keep Claude/Codex/local models behind adapter interfaces.
6. Prefer small, testable modules over large monolithic code.
7. Add or update tests for every functional change.
8. Do not destructively move existing personal or investment folders. If
   importing is needed, create a safe copy or ask for the source path.

## 6. Why "OS kernel" is the right metaphor

An OS kernel does not do the work of applications; it **schedules, isolates,
and mediates** them. AMMO schedules capabilities, isolates the kernel from the
data it governs, and mediates every model call through adapters. Applications
(system packs) are built *on* the kernel — they do not *become* the kernel.
