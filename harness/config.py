"""Central configuration. Every value can be overridden with an environment variable."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERIFIER_DIR = ROOT / "verifier"
RUNS_DIR = Path(os.getenv("GAMESMITH_RUNS_DIR", ROOT / "runs"))
PLAYBOOK_PATH = ROOT / "playbook.md"


def _env_int(name: str, default: int) -> int:
    return int(os.getenv(name, default))


def _env_float(name: str, default: float) -> float:
    return float(os.getenv(name, default))


@dataclass(frozen=True)
class Budgets:
    """Hard limits per run. Hitting any of them ends the run as `budget_exceeded`."""

    max_steps: int = field(default_factory=lambda: _env_int("GAMESMITH_MAX_STEPS", 20))
    max_tokens: int = field(default_factory=lambda: _env_int("GAMESMITH_MAX_TOKENS", 200_000))
    max_seconds: float = field(default_factory=lambda: _env_float("GAMESMITH_MAX_SECONDS", 600))


MODEL = os.getenv("GAMESMITH_MODEL", "claude-sonnet-5-5")
# USD per million tokens, used for cost estimates only. Set these to your model's real prices.
PRICE_IN_PER_MTOK = _env_float("GAMESMITH_PRICE_IN", 3.0)
PRICE_OUT_PER_MTOK = _env_float("GAMESMITH_PRICE_OUT", 15.0)

NODE_CAP = _env_int("GAMESMITH_NODE_CAP", 200_000)
COMPILE_TIMEOUT_S = _env_float("GAMESMITH_COMPILE_TIMEOUT", 60)
VERIFY_TIMEOUT_S = _env_float("GAMESMITH_VERIFY_TIMEOUT", 60)
# "auto" self-tests Node's permission model at startup; "on" requires it; "off" disables it.
NODE_PERMISSION = os.getenv("GAMESMITH_NODE_PERMISSION", "auto")

MAX_FILE_BYTES = 100_000
MAX_FILES = 20
ALLOWED_SUFFIXES = {".ts", ".md", ".json", ".txt"}


def cost_usd(tokens_in: int, tokens_out: int, price_in: float | None = None, price_out: float | None = None) -> float:
    price_in = PRICE_IN_PER_MTOK if price_in is None else price_in
    price_out = PRICE_OUT_PER_MTOK if price_out is None else price_out
    return round(tokens_in / 1e6 * price_in + tokens_out / 1e6 * price_out, 5)
