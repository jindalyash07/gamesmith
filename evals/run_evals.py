"""Benchmark the agent on a suite of game specs.

    python -m evals.run_evals                                  # mock, train+heldout, 3 repeats
    python -m evals.run_evals --provider anthropic --split heldout --repeats 1
    python -m evals.run_evals --provider gemini --split heldout --repeats 1 --workers 1

Reports pass rate, first-try pass rate, steps, tokens, cost, latency and a failure taxonomy.
Repeats use different seeds, so the mock's randomness averages out.
"""
from __future__ import annotations

import argparse
import json
import statistics
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from harness import config
from harness.agent import RunResult, run_agent
from harness.providers import PROVIDERS, make_provider

SPECS_PATH = Path(__file__).parent / "specs.json"
RESULTS_DIR = Path(__file__).parent / "results"


def load_specs(split: str) -> list[dict[str, str]]:
    data = json.loads(SPECS_PATH.read_text(encoding="utf-8"))
    return data["train"] + data["heldout"] if split == "all" else data[split]


def _pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


def summarise(results: list[RunResult]) -> dict[str, Any]:
    n = len(results)
    passed = [r for r in results if r.success]
    first_try = [r for r in passed if not r.gate_failures]
    failures = Counter(r.final_category for r in results if not r.success)
    fixed_along_the_way = Counter(f["category"] for r in results for f in r.gate_failures)
    return {
        "runs": n,
        "provider": results[0].provider if results else None,
        "model": results[0].model if results else None,
        "pass_rate": round(len(passed) / n, 3) if n else 0.0,
        "first_try_pass_rate": round(len(first_try) / n, 3) if n else 0.0,
        "avg_steps": round(statistics.mean(r.steps for r in results), 2) if n else 0.0,
        "avg_tokens": round(statistics.mean(r.tokens_in + r.tokens_out for r in results)) if n else 0,
        "total_cost_usd": round(sum(r.cost_usd for r in results), 4),
        "p50_duration_s": _pct([r.duration_s for r in results], 0.5),
        "p95_duration_s": _pct([r.duration_s for r in results], 0.95),
        "final_failures": dict(failures.most_common()),
        "all_gate_failures": dict(fixed_along_the_way.most_common()),
    }


def run_suite(specs: list[dict[str, str]], provider_name: str, *, playbook: str = "", repeats: int = 1,
              seed: int = 0, workers: int = 4, label: str = "eval") -> tuple[list[RunResult], dict[str, Any]]:
    jobs = [(spec, r) for r in range(repeats) for spec in specs]

    def one(job: tuple[dict[str, str], int]) -> RunResult:
        spec, r = job
        job_seed = seed + 1000 * r + int(spec["id"][1:]) + (500 if spec["id"].startswith("h") else 0)
        provider = make_provider(provider_name, seed=job_seed, playbook=playbook)
        return run_agent(spec["spec"], provider, spec_id=spec["id"], playbook=playbook,
                         run_id=f"{label}-{spec['id']}-r{r}-{time.strftime('%H%M%S')}-{job_seed}")

    with ThreadPoolExecutor(max_workers=workers) as pool:
        results = list(pool.map(one, jobs))
    return results, summarise(results)


def print_summary(title: str, s: dict[str, Any]) -> None:
    print(f"\n== {title} ==")
    print(f"runs {s['runs']} | pass {s['pass_rate']:.0%} | first-try pass {s['first_try_pass_rate']:.0%} | "
          f"avg steps {s['avg_steps']} | avg tokens {s['avg_tokens']:,} | cost ${s['total_cost_usd']} | "
          f"p50 {s['p50_duration_s']}s p95 {s['p95_duration_s']}s")
    print(f"failures that ended runs: {s['final_failures'] or 'none'}")
    print(f"all gate failures (incl. ones the agent fixed): {s['all_gate_failures'] or 'none'}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="mock", choices=PROVIDERS)
    ap.add_argument("--split", default="all", choices=["train", "heldout", "all"])
    ap.add_argument("--repeats", type=int, default=3)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--playbook", type=Path, default=config.PLAYBOOK_PATH,
                    help="Playbook file; keep one per model, e.g. playbook_gemini.md.")
    ap.add_argument("--no-playbook", action="store_true")
    args = ap.parse_args()

    playbook = "" if args.no_playbook or not args.playbook.exists() else args.playbook.read_text(encoding="utf-8")
    results, summary = run_suite(load_specs(args.split), args.provider, playbook=playbook, repeats=args.repeats,
                                 seed=args.seed, workers=args.workers)
    print_summary(f"{args.provider} / {args.split} / playbook={'yes' if playbook.strip() else 'no'}", summary)

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"eval_{args.provider}_{args.split}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"kind": "eval", "args": {k: str(v) for k, v in vars(args).items()},
                               "playbook_used": bool(playbook.strip()), "summary": summary,
                               "runs": [r.to_dict() for r in results]}, indent=2), encoding="utf-8")
    print(f"\nSaved {out}")


if __name__ == "__main__":
    main()
