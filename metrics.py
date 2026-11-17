"""Aggregate run traces into an operational summary, optionally in Prometheus text format.

    python metrics.py                    # human-readable summary of everything in runs/
    python metrics.py --prom metrics.prom  # also write Prometheus exposition format
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from harness import config
from harness.tracing import load_trace


def pct(values: list[float], q: float) -> float:
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))] if ordered else 0.0


def collect(runs_dir: Path) -> dict:
    ends, latency, gates, tools, security = [], defaultdict(list), Counter(), Counter(), Counter()
    for trace in sorted(runs_dir.glob("*/trace.jsonl")):
        for e in load_trace(trace):
            t = e["type"]
            if t == "run_end":
                ends.append(e)
            elif t == "llm_call":
                latency["llm_call"].append(e["duration_ms"])
            elif t == "tool_call":
                latency[f"tool:{e['tool']}"].append(e["duration_ms"])
                tools[(e["tool"], "error" if e.get("is_error") else "ok")] += 1
            elif t == "gate":
                gates[e.get("category") or "passed"] += 1
            elif t in ("security_flag", "blocked_action", "secret_reference"):
                security[t] += 1
    return {"ends": ends, "latency": latency, "gates": gates, "tools": tools, "security": security}


def to_prometheus(m: dict) -> str:
    lines = [
        "# HELP gamesmith_runs_total Agent runs by outcome.", "# TYPE gamesmith_runs_total counter",
        *[f'gamesmith_runs_total{{outcome="{o}"}} {n}' for o, n in Counter(e["outcome"] for e in m["ends"]).items()],
        "# HELP gamesmith_tokens_total Tokens used.", "# TYPE gamesmith_tokens_total counter",
        f'gamesmith_tokens_total{{direction="in"}} {sum(e["tokens_in"] for e in m["ends"])}',
        f'gamesmith_tokens_total{{direction="out"}} {sum(e["tokens_out"] for e in m["ends"])}',
        "# HELP gamesmith_gate_results_total Gate results by category.", "# TYPE gamesmith_gate_results_total counter",
        *[f'gamesmith_gate_results_total{{category="{c}"}} {n}' for c, n in m["gates"].items()],
        "# HELP gamesmith_tool_calls_total Tool calls.", "# TYPE gamesmith_tool_calls_total counter",
        *[f'gamesmith_tool_calls_total{{tool="{t}",status="{s}"}} {n}' for (t, s), n in m["tools"].items()],
        "# HELP gamesmith_security_events_total Security flags and blocked actions.",
        "# TYPE gamesmith_security_events_total counter",
        *[f'gamesmith_security_events_total{{type="{t}"}} {n}' for t, n in m["security"].items()],
        "# HELP gamesmith_latency_ms Step latency percentiles.", "# TYPE gamesmith_latency_ms gauge",
    ]
    for op, vals in m["latency"].items():
        for q in (0.5, 0.95):
            lines.append(f'gamesmith_latency_ms{{op="{op}",quantile="{q}"}} {pct(vals, q)}')
    return "\n".join(lines) + "\n"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--runs", type=Path, default=config.RUNS_DIR)
    ap.add_argument("--prom", type=Path, help="Write Prometheus text format to this file.")
    args = ap.parse_args()

    m = collect(args.runs)
    ends = m["ends"]
    if not ends:
        print(f"No completed runs in {args.runs}.")
        return
    passed = sum(e["success"] for e in ends)
    print(f"Runs: {len(ends)} | passed {passed} ({passed / len(ends):.0%}) | "
          f"tokens {sum(e['tokens_in'] + e['tokens_out'] for e in ends):,} | "
          f"est. cost ${sum(e['cost_usd'] for e in ends):.2f}")
    print("\nLatency (ms)          p50      p95     count")
    for op, vals in sorted(m["latency"].items()):
        print(f"  {op:<18}{pct(vals, .5):>7.0f}{pct(vals, .95):>9.0f}{len(vals):>10}")
    print("\nGate results:", dict(m["gates"].most_common()))
    print("Outcomes:", dict(Counter(e["outcome"] for e in ends)))
    print("Security:", dict(m["security"]) or "none")
    if args.prom:
        args.prom.write_text(to_prometheus(m), encoding="utf-8")
        print(f"\nWrote {args.prom}")


if __name__ == "__main__":
    main()
