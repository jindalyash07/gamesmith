# GameSmith

**An agent platform that builds, verifies and repairs puzzle games on its own, and gets better at it from its own failures.**

You give it a one-line spec ("Tower of Hanoi where each level adds a disk"). A Claude agent writes the game in TypeScript inside a confined workspace, runs it through quality gates it cannot tamper with, reads the feedback, fixes its mistakes and submits. Every step is traced. Failures are distilled into a playbook that is accepted only if it improves results on held-out specs. A red-team suite checks that prompt injections cannot escape the sandbox.

It covers the four parts of running autonomous agents in production: **harnesses, reliability engineering, self-improvement and security.**

## Architecture

```
 spec (untrusted) ─► security.scan ─► security_flag event
        │
        ▼
 ┌──────────────────────── agent loop (harness/agent.py) ────────────────────────┐
 │  Claude ──tool_use──► ToolBox: list_files · read_file · write_file · verify · submit │
 │    ▲                        │  confined to runs/<id>/workspace (path allowlist)        │
 │    └──── tool_result ◄──────┤                                                          │
 │   budgets: steps · tokens · wall-clock     circuit breaker on provider errors          │
 └─────────────────────────────┼─────────────────────────────────────────────────────────┘
                               ▼
        Quality gates (harness-owned; the agent can run them, never change them)
          1. lint: no imports / process / eval / network / timers
          2. strict tsc compile, ES2022 lib only, no Node typings
          3. black-box verifier under Node's permission model (no fs writes, reads only its own files)
             interface · purity · BFS solvability · difficulty curve
                               │
                               ▼
        runs/<id>/trace.jsonl ──► metrics.py (summary + Prometheus)
                               └─► improve.py ──► playbook.md (accepted only if held-out evals improve)
```

### The key design idea

Every game implements the same five-member contract (`levels`, `initialState`, `legalMoves`, `applyMove`, `isWon`). That lets **one generic breadth-first-search verifier check any puzzle genre** as a black box: it proves every level is solvable, computes each level's optimal move count, catches `applyMove` mutating its input, and checks that difficulty never drops. The model is never trusted to grade itself; its feedback comes from an exact solver.

## Repository

| Path | What it does |
|---|---|
| `verifier/src/verify.ts` | Generic BFS verifier with node cap, purity and difficulty checks |
| `verifier/src/contract.ts` | The game contract, given verbatim to the agent |
| `verifier/examples/` | Four reference games (sliding tile, Lights Out, Hanoi, water jugs) |
| `harness/agent.py` | Tool-use loop, budgets, circuit breaker, run results |
| `harness/tools.py` | The agent's tools; all file access goes through the workspace |
| `harness/sandbox.py` | Path confinement (`..`, absolute, drive letters, symlinks), minimal-env subprocesses |
| `harness/gates.py` | Lint → compile → verify, mapped to a failure taxonomy; self-tests Node's permission model |
| `harness/security.py` | Injection detection, untrusted-data wrapping, forbidden-API lint, secret-reference detection |
| `harness/tracing.py` | JSONL trace events with timed spans |
| `harness/providers.py` | Claude provider, plus a seeded mock agent with realistic failure modes for offline tests |
| `harness/openai_compat.py` | Gemini and any OpenAI-compatible API: message-format translation, thought-signature passthrough, rate-limit backoff |
| `compare.py` | Side-by-side model comparison from saved results (console or Markdown) |
| `evals/run_evals.py` | Pass rate, first-try pass rate, steps, tokens, cost, latency, failure taxonomy |
| `evals/redteam.py` | Six injection cases (spec and file vectors) with a canary secret |
| `improve.py` | Trace-driven self-improvement with a held-out acceptance gate |
| `metrics.py` | Operational summary and Prometheus exposition format |

## Setup (Windows PowerShell)

```powershell
cd D:\GameSmith
.\setup.ps1                      # venv, Python deps, verifier build, all tests
.venv\Scripts\Activate.ps1
```

Requires Python 3.10+ and Node.js 20+ (Node 22+ recommended for the stable permission model).

## Run it

```powershell
# Offline, no API key needed (mock agent)
python -m harness.cli "Tower of Hanoi where each level adds a disk"
python -m evals.run_evals --repeats 3
python -m evals.redteam
python improve.py --rounds 2 --repeats 4
python metrics.py --prom metrics.prom

# With Claude
$env:ANTHROPIC_API_KEY = "sk-ant-..."
$env:GAMESMITH_MODEL   = "claude-sonnet-5-5"     # any model with tool use
python -m harness.cli "A river-crossing puzzle with a wolf, a goat and a cabbage" --provider anthropic
python improve.py --provider anthropic --rounds 1 --repeats 1 --playbook playbook_claude.md
python -m evals.redteam --provider anthropic

# With Gemini (free tier; key from aistudio.google.com). --workers 1 stays under free-tier rate limits.
$env:GEMINI_API_KEY = "..."
$env:GEMINI_MODEL   = "gemini-3.8-flash"          # any Gemini model with function calling
python -m harness.cli "A river-crossing puzzle with a wolf, a goat and a cabbage" --provider gemini
python improve.py --provider gemini --rounds 1 --repeats 1 --workers 1 --playbook playbook_gemini.md
python -m evals.redteam --provider gemini

# Side-by-side comparison of the latest results for each model
python compare.py
python compare.py --markdown      # paste into this README
```

`improve.py` already runs the held-out baseline (before) and the candidate playbook (after), so one command per model gives you the full comparison. Each model keeps its own playbook, so one model's lessons never leak into the other's run. Any other OpenAI-compatible API (Groq, OpenRouter, a local server) works with `--provider openai_compat` and the `OPENAI_COMPAT_BASE_URL`, `OPENAI_COMPAT_API_KEY` and `OPENAI_COMPAT_MODEL` variables.

Each run leaves its game, compiled output and full trace in `runs/<run_id>/`.

## Results

All numbers below are real runs with **Claude Sonnet 5.5** (`claude-sonnet-5-5`), unless marked as mock.

### Self-improvement on held-out specs

Rules were learned only from the 12 train specs, then tested on 8 held-out specs the playbook never saw. Both arms ran in the same session; the second experiment repeats each held-out spec 3 times.

| Experiment | Playbook | Runs | Pass | First-try pass | Avg steps | Avg tokens | Cost/game | p95 latency |
|---|---|---|---|---|---|---|---|---|
| A (1 run per spec) | none | 8 | 100% | 62% | 3.12 | 13,700 | $0.074 | 51.3 s |
| A | learned | 8 | 100% | **88%** | **2.25** | **9,697** | $0.056 | **29.9 s** |
| B (3 runs per spec) | none | 24 | 100% | 62% | 3.08 | 14,054 | $0.077 | 64.7 s |
| B | learned | 24 | 100% | **75%** | **2.83** | 14,792 | $0.076 | **49.5 s** |

What the data says:

- **Claude writes valid puzzle logic but misjudges difficulty.** Almost every training failure (all 4 in A, 13 of 14 in B) was `difficulty_not_increasing`: levels Claude believed were ordered easy-to-hard weren't, according to the exact solver. All the learned rules target this ("measure difficulty with the solver, never intuition").
- **The larger sample shrank the effect.** A 62% → 88% first-try gain on 8 runs became 62% → 75% on 24 runs. The 24-run number is the one to trust.
- **Rules only partly transfer.** Held-out failures were mostly `unsolvable_level` (10 of 15), a category that barely appeared in training, so no rule addressed it. More diverse training specs, or a second round, is the obvious next step.
- **Playbooks cost tokens.** In experiment B the rules cut steps by 8% and p95 latency by 24%, but tokens per game rose 5%, because every prompt now carries five rules. Pruning rules that stop helping is on the roadmap.
- Final pass rate is 100% in every arm. Sonnet always gets there through the verifier's feedback, so first-try success and cost are the metrics that discriminate.

### Red team

| Agent | Attacks | Detected | Malicious actions attempted | Attacks succeeded | Games still built |
|---|---|---|---|---|---|
| Claude Sonnet 5.5 | 5 | 5 | **0** | **0** | 5/5 |
| Mock in "gullible" mode (always takes the bait) | 5 | 5 | 15 | **0** | 5/5 |

Claude ignored every injected instruction. The mock run shows the harness contains a compromised agent anyway: all 15 attempted actions (reading `../../.env`, overwriting the gates, exporting secrets) were blocked. Benign control: 0 false positives.

### Mock agent (offline simulation)

The seeded mock agent exercises the whole pipeline with no API key. Over two improvement rounds it went from 22% → 56% → 84% first-try on held-out specs. These are **simulated** numbers that only show the machinery works; they say nothing about model behaviour.

### Model comparison

`compare.py` builds this table for any set of providers. A Gemini run is in progress: the free tier returned HTTP 503 (overloaded) during the first attempt.

**Tests:** 51 pytest tests (sandbox escapes, the Gemini adapter against a fake HTTP server, gate categories, budgets, circuit breaker, injection containment, metrics, acceptance logic) and 13 verifier tests.

## Design decisions and trade-offs

- **Gates over self-assessment.** The agent can call `verify` as often as it likes, but only harness-owned gates decide success. A model that just *says* it is done gets nudged and eventually runs out of budget (`test_model_cannot_claim_success_without_gates`).
- **Containment over detection.** Injection regexes are easy to evade, so they only flag and log. The guarantees are structural: path confinement, no secrets in the sandbox environment, the build directory outside the agent's reach, and Node's permission model while running generated code. `test_lint_bypass_is_still_contained_by_node_permissions` slips a filesystem read past the lint (`[].constructor.constructor("return this")()`) and shows the permission model still denies it.
- **Held-out acceptance for self-improvement.** Rules are learned only from train-split failures and kept only if a paired held-out comparison improves (pass rate, then first-try pass rate, then steps). This stops the playbook from overfitting or growing without bound.
- **Exact verification limits the genre space.** BFS needs small, finite state spaces (capped at 200k states per level). Large or continuous games would need sampled playtesting with a bot instead of proofs. That's a deliberate trade of generality for certainty.
- **Mock provider.** It makes the whole platform testable offline and in CI at zero cost, but its numbers are simulations, not model behaviour.

## Limitations and next steps

- Run generated code in a Docker container with no network and CPU/memory limits, on top of Node's permission model
- Player-experience evals: a playtest bot measuring branching factor and dead-ends, plus an LLM judge for theme, calibrated against human ratings
- Grafana dashboard on the Prometheus output; alerting on pass-rate and cost regressions
- More diverse training specs, so learned rules cover failure modes such as `unsolvable_level` that show up mainly on held-out specs
- Playbook pruning: ablate each rule on held-out data and drop the ones that no longer help
- Expand the red team with multi-turn and encoded injections, and track attack success per model version
