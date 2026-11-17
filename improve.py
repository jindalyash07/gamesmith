"""Self-improvement loop: learn playbook rules from failures, keep them only if held-out evals improve.

    python improve.py                                   # mock, 2 rounds
    python improve.py --provider anthropic --rounds 1 --repeats 1 --playbook playbook_claude.md
    python improve.py --provider gemini --rounds 1 --repeats 1 --workers 1 --playbook playbook_gemini.md

Each round:
  1. run the TRAIN specs with the current playbook and collect every gate failure from the traces
  2. ask the model to distil those failures into a few general rules (candidate playbook)
  3. run the HELD-OUT specs with the current and the candidate playbook, using identical seeds
  4. accept the candidate only if it is better on held-out data:
       pass rate first, then first-try pass rate, then fewer steps
Held-out specs are never used to write rules, so an accepted rule must generalise.
"""
from __future__ import annotations

import argparse
import json
import time
from collections import Counter, defaultdict
from pathlib import Path

from evals.run_evals import RESULTS_DIR, load_specs, print_summary, run_suite
from harness import config
from harness.providers import PROVIDERS, make_provider


def failure_report(results) -> str:
    counts: Counter[str] = Counter()
    examples: dict[str, list[str]] = defaultdict(list)
    for r in results:
        for f in r.gate_failures:
            counts[f["category"]] += 1
            if len(examples[f["category"]]) < 3:
                examples[f["category"]].append(f["message"][:200])
    lines = [f"{cat}: {n}" for cat, n in counts.most_common()]
    for cat, msgs in examples.items():
        lines.append(f"\nExamples of {cat}:")
        lines += [f"  - {m}" for m in msgs]
    return "\n".join(lines)


def score(summary: dict) -> tuple[float, float, float]:
    return (summary["pass_rate"], summary["first_try_pass_rate"], -summary["avg_steps"])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--provider", default="mock", choices=PROVIDERS)
    ap.add_argument("--rounds", type=int, default=2)
    ap.add_argument("--repeats", type=int, default=5, help="Seeds per spec (use 1 with a real model to save cost).")
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--playbook", type=Path, default=config.PLAYBOOK_PATH,
                    help="Playbook file to read and update; keep one per model.")
    args = ap.parse_args()

    playbook = args.playbook.read_text(encoding="utf-8") if args.playbook.exists() else ""
    train, heldout = load_specs("train"), load_specs("heldout")
    history = []

    for rnd in range(1, args.rounds + 1):
        print(f"\n######## Round {rnd} ########")
        train_results, train_summary = run_suite(train, args.provider, playbook=playbook, repeats=args.repeats,
                                                 seed=args.seed + 10_000 * rnd, workers=args.workers, label=f"improve{rnd}-train")
        print_summary("train, current playbook", train_summary)

        report = failure_report(train_results)
        if not report:
            print("No failures on train; nothing to learn.")
            break
        new_rules = make_provider(args.provider).distill(report, playbook).strip()
        if not new_rules:
            print("Model proposed no new rules; stopping.")
            break
        candidate = (playbook.rstrip() + "\n" + new_rules).strip() + "\n"
        print(f"\nProposed rules:\n{new_rules}")

        heldout_seed = args.seed + 20_000 * rnd
        _, base = run_suite(heldout, args.provider, playbook=playbook, repeats=args.repeats, seed=heldout_seed,
                            workers=args.workers, label=f"improve{rnd}-base")
        _, cand = run_suite(heldout, args.provider, playbook=candidate, repeats=args.repeats, seed=heldout_seed,
                            workers=args.workers, label=f"improve{rnd}-cand")
        print_summary("held-out, current playbook", base)
        print_summary("held-out, candidate playbook", cand)

        accepted = score(cand) > score(base)
        print(f"\nDecision: {'ACCEPT' if accepted else 'REJECT'} candidate playbook")
        history.append({"round": rnd, "new_rules": new_rules, "accepted": accepted,
                        "train": train_summary, "heldout_base": base, "heldout_candidate": cand})
        if accepted:
            playbook = candidate
            args.playbook.write_text(playbook, encoding="utf-8")

    RESULTS_DIR.mkdir(exist_ok=True)
    out = RESULTS_DIR / f"improve_{args.provider}_{time.strftime('%Y%m%d-%H%M%S')}.json"
    out.write_text(json.dumps({"kind": "improve", "provider": args.provider, "playbook": str(args.playbook),
                               "rounds": history}, indent=2), encoding="utf-8")
    print(f"\nSaved {out}\nFinal playbook ({args.playbook.name}):\n{playbook or '(empty)'}")


if __name__ == "__main__":
    main()
