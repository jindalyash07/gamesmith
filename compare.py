"""Compare models side by side from saved eval and self-improvement results.

    python compare.py                       # latest results for each real provider in evals/results/
    python compare.py --markdown            # same, as a Markdown table for the README
    python compare.py evals/results/a.json evals/results/b.json   # specific files
    python compare.py --include-mock        # include simulated mock runs

For improve_*.json files it shows each round's held-out "before" and "after" rows, so you
can see how much self-improvement helped each model on specs it never learned from.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

RESULTS_DIR = Path(__file__).parent / "evals" / "results"
COLUMNS = ["Model", "Setting", "Runs", "Pass", "First-try", "Avg steps", "Avg tokens", "Cost/game", "p50 s", "Top failure"]


def _label(summary: dict, fallback: str) -> str:
    model = summary.get("model")
    provider = summary.get("provider") or fallback
    return f"{provider}: {model}" if model else provider


def _top_failure(summary: dict) -> str:
    failures = summary.get("all_gate_failures") or {}
    if not failures:
        return "-"
    name, count = max(failures.items(), key=lambda kv: kv[1])
    return f"{name} ({count})"


def _row(summary: dict, setting: str, fallback: str) -> list[str]:
    runs = summary["runs"] or 1
    return [
        _label(summary, fallback), setting, str(summary["runs"]),
        f"{summary['pass_rate']:.0%}", f"{summary['first_try_pass_rate']:.0%}",
        f"{summary['avg_steps']:.2f}", f"{summary['avg_tokens']:,}",
        f"${summary['total_cost_usd'] / runs:.4f}", f"{summary['p50_duration_s']:.1f}", _top_failure(summary),
    ]


def rows_from_file(path: Path) -> list[list[str]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, dict) and data.get("kind") == "improve":
        rows = []
        for rnd in data["rounds"]:
            n = rnd["round"]
            rows.append(_row(rnd["heldout_base"], f"held-out, before round {n}", data["provider"]))
            verdict = "accepted" if rnd["accepted"] else "rejected"
            rows.append(_row(rnd["heldout_candidate"], f"held-out, after round {n} ({verdict})", data["provider"]))
        return rows
    if isinstance(data, dict) and "summary" in data:
        args = data.get("args", {})
        setting = f"{args.get('split', '?')}, {'with playbook' if data.get('playbook_used') else 'no playbook'}"
        return [_row(data["summary"], setting, args.get("provider", "?"))]
    raise ValueError(f"{path} is not an eval or improve result file")


def latest_files(include_mock: bool) -> list[Path]:
    """Newest eval file and newest improve file for each provider."""
    newest: dict[tuple[str, str], Path] = {}
    for path in sorted(RESULTS_DIR.glob("*.json")):
        parts = path.stem.split("_")  # eval_<provider>_<split>_<ts> | improve_<provider>_<ts>
        if parts[0] not in ("eval", "improve") or len(parts) < 3:
            continue
        provider = parts[1] if parts[1] != "openai" else "openai_compat"
        if provider == "mock" and not include_mock:
            continue
        newest[(parts[0], provider)] = path  # sorted by name, and names end in a timestamp
    return [newest[k] for k in sorted(newest, key=lambda k: (k[1], k[0]))]


def render(rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(COLUMNS) + " |", "|" + "---|" * len(COLUMNS)]
        lines += ["| " + " | ".join(r) + " |" for r in rows]
        return "\n".join(lines)
    widths = [max(len(c), *(len(r[i]) for r in rows)) for i, c in enumerate(COLUMNS)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join([fmt.format(*COLUMNS), fmt.format(*("-" * w for w in widths))] + [fmt.format(*r) for r in rows])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="*", type=Path)
    ap.add_argument("--markdown", action="store_true")
    ap.add_argument("--include-mock", action="store_true")
    args = ap.parse_args()

    files = args.files or latest_files(args.include_mock)
    if not files:
        print(f"No result files found in {RESULTS_DIR}. Run evals or improve.py first (or add --include-mock).")
        return
    rows = [row for path in files for row in rows_from_file(path)]
    print(render(rows, args.markdown))
    print("\nFiles: " + ", ".join(p.name for p in files))
    print("Cost/game uses the prices configured per provider (Gemini free tier defaults to $0).")


if __name__ == "__main__":
    main()
