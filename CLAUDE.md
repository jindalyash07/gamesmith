# GameSmith: notes for Claude Code

An agent platform that builds, verifies and repairs small turn-based puzzle games. See README.md for the full picture.
Owner: Yash. This is a portfolio project for agentic-systems roles, so every change must stay simple enough to explain in an interview.

## Layout

- `verifier/` (TypeScript, harness-owned): `src/verify.ts` generic BFS verifier, `src/contract.ts` game contract, `examples/` reference games, `test/`
- `harness/` (Python): `agent.py` loop, `tools.py`, `sandbox.py`, `gates.py`, `security.py`, `tracing.py`, `providers.py`, `config.py`, `cli.py`
- `evals/`: `specs.json` (train/heldout), `run_evals.py`, `redteam.json`, `redteam.py`
- `improve.py` self-improvement, `metrics.py` observability, `tests/` pytest
- `runs/<run_id>/{workspace,build,trace.jsonl}` is generated output and is gitignored

## Commands

- Setup: `.\setup.ps1` (Windows) or `npm install --prefix verifier && npm run build --prefix verifier && pip install -r requirements.txt`
- Tests: `python -m pytest -q` and `npm test --prefix verifier`. Both must pass before every commit.
- After editing `verifier/src` or `verifier/examples`, rebuild with `npm run build --prefix verifier`.

## Invariants (do not break these)

- The agent's tools only touch `runs/<id>/workspace`. All paths go through `Workspace.resolve`.
- Gates are harness-owned. The agent can run them, never modify them, and only gates decide success.
- Subprocesses get `sandbox.minimal_env()`, so no API keys reach generated code.
- Spec text and file contents are wrapped with `security.wrap_untrusted` before they reach the model.
- Every LLM call, tool call and gate result is a trace event.
- Tests use `MockProvider` and never need network access or an API key.
- New failure categories must be added to the taxonomy in README, `gates.py` and `providers.MOCK_RULES`.

## Failure taxonomy

`build_error`, `forbidden_api`, `interface_violation`, `unsolvable_level`, `difficulty_not_increasing`,
`unverifiable_state_space`, `verifier_timeout`, plus run outcomes `budget_exceeded`, `provider_error`.
