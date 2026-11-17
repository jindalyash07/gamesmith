"""Build one game from a spec.

    python -m harness.cli "A tower-of-hanoi variant with 6 levels"            # offline mock agent
    python -m harness.cli "A lights-out puzzle" --provider anthropic         # real Claude
    python -m harness.cli "A lights-out puzzle" --provider gemini            # Gemini (GEMINI_API_KEY)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from . import config
from .agent import run_agent
from .gates import permission_mode
from .providers import PROVIDERS, make_provider


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec", help="One-line description of the game to build.")
    ap.add_argument("--provider", default="mock", choices=PROVIDERS)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--playbook", type=Path, default=config.PLAYBOOK_PATH, help="Playbook file to use.")
    ap.add_argument("--no-playbook", action="store_true", help="Run without any playbook.")
    args = ap.parse_args()

    playbook = "" if args.no_playbook or not args.playbook.exists() else args.playbook.read_text(encoding="utf-8")
    sandbox = permission_mode()
    if sandbox == "off":
        print("WARNING: Node permission model unavailable; generated code runs without filesystem restrictions.")
    result = run_agent(args.spec, make_provider(args.provider, seed=args.seed, playbook=playbook), playbook=playbook)
    print(json.dumps(result.to_dict(), indent=2))
    print(f"\n{'PASSED' if result.success else 'FAILED'} in {result.steps} steps. Game and trace: {result.run_dir}")


if __name__ == "__main__":
    main()
