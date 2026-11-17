"""LLM providers.

AnthropicProvider talks to Claude with native tool use.
MockProvider is a deterministic, seeded stand-in that behaves like a fallible agent
(it writes buggy games, reads feedback, fixes some bugs and not others). It lets the
whole platform, including evals and self-improvement, run offline in tests and CI.
Numbers produced with the mock are simulations; real numbers come from real models.
Gemini and other OpenAI-compatible APIs live in openai_compat.py.
"""
from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from typing import Any

from . import config, security


class ProviderError(Exception):
    pass


@dataclass
class Response:
    content: list[dict[str, Any]]
    tokens_in: int
    tokens_out: int
    stop_reason: str


DISTILL_PROMPT = """You maintain a playbook of short rules for an AI agent that writes TypeScript puzzle games.
Below are failure reports from recent runs, grouped by category, with example error messages.
Write at most 5 NEW rules that would prevent the most common failures.
Format each rule as one line: "- (<category>) <rule>". Be concrete and general, not specific to one game.
Do not repeat rules already in the current playbook. Output only the rules."""


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, model: str | None = None):
        import anthropic

        self._anthropic = anthropic
        self.client = anthropic.Anthropic(max_retries=4, timeout=180)  # SDK retries 429/5xx with backoff
        self.model = model or config.MODEL
        self.price_in = config.PRICE_IN_PER_MTOK
        self.price_out = config.PRICE_OUT_PER_MTOK

    def respond(self, system: str, messages: list[dict], tools: list[dict]) -> Response:
        try:
            resp = self.client.messages.create(model=self.model, max_tokens=8192, system=system,
                                               messages=messages, tools=tools)
        except self._anthropic.APIError as exc:
            raise ProviderError(f"{type(exc).__name__}: {exc}") from exc
        content = [block.model_dump(exclude_none=True) for block in resp.content]
        return Response(content, resp.usage.input_tokens, resp.usage.output_tokens, resp.stop_reason or "")

    def distill(self, failure_report: str, playbook: str) -> str:
        try:
            resp = self.client.messages.create(
                model=self.model, max_tokens=800, system=DISTILL_PROMPT,
                messages=[{"role": "user", "content": f"Current playbook:\n{playbook or '(empty)'}\n\nFailures:\n{failure_report}"}],
            )
        except self._anthropic.APIError as exc:
            raise ProviderError(str(exc)) from exc
        return "".join(b.text for b in resp.content if b.type == "text").strip()


# --------------------------------------------------------------------------------------
# Mock agent
# --------------------------------------------------------------------------------------

GENRE_KEYWORDS = {
    "sliding": ["slid", "tile", "8-puzzle", "fifteen"],
    "lights": ["light", "lamp", "switch", "toggle", "bulb"],
    "hanoi": ["hanoi", "disk", "disc", "tower", "stack"],
    "jugs": ["jug", "water", "pour", "bucket", "measure"],
}

BUG_RATES = {
    "build_error": 0.20,
    "unsolvable_level": 0.15,
    "difficulty_not_increasing": 0.15,
    "interface_violation": 0.10,
    "forbidden_api": 0.08,
}

MOCK_RULES = {
    "build_error": "- (build_error) Annotate every variable with the type it really holds and re-read code for type mismatches before verifying.",
    "unsolvable_level": "- (unsolvable_level) Construct each level by applying legal moves backwards from a solved state, so it is solvable by construction.",
    "difficulty_not_increasing": "- (difficulty_not_increasing) Order levels by their optimal move count and make the last level clearly harder than the first.",
    "interface_violation": "- (interface_violation) Export all five contract members and at least five levels; never mutate the input state in applyMove.",
    "forbidden_api": "- (forbidden_api) Games are pure logic: no imports, process, globals, timers or debug flags.",
    "verifier_timeout": "- (verifier_timeout) Keep state spaces small and avoid unbounded loops.",
    "unverifiable_state_space": "- (unverifiable_state_space) Keep each level's reachable state space well under 200,000 states.",
}


def _template(genre: str) -> str:
    return (config.VERIFIER_DIR / "examples" / f"{genre}.ts").read_text(encoding="utf-8")


def _level_lines(src: str) -> tuple[list[str], int, int]:
    lines = src.splitlines()
    start = next(i for i, ln in enumerate(lines) if "@levels-start" in ln) + 2  # skip `export const levels = [`
    end = next(i for i, ln in enumerate(lines) if "@levels-end" in ln) - 1  # stop before `];`
    return lines, start, end


def inject_bug(src: str, bug: str | None) -> str:
    """Apply one realistic mistake to a correct reference game."""
    if bug is None:
        return src
    lines, start, end = _level_lines(src)
    entries = lines[start:end]
    if bug == "build_error":
        lines.insert(end + 1, 'const DIFFICULTY_SCALE: number = "linear";')
    elif bug == "unsolvable_level":
        bad = re.search(r"@unsolvable-level: (.*)", src).group(1).strip()
        entries[-1] = f"  {bad},"
        lines[start:end] = entries
    elif bug == "difficulty_not_increasing":
        lines[start:end] = entries[::-1]
    elif bug == "interface_violation":
        lines[start:end] = entries[:3]
    elif bug == "forbidden_api":
        lines.insert(end + 1, 'declare const process: { env: Record<string, string | undefined> };\n'
                              'const DEBUG = process.env.DEBUG === "1";')
    elif bug == "exfiltrate_secret":
        lines.insert(end + 1, 'declare const process: { env: Record<string, string | undefined> };\n'
                              'export const leak = process.env.ANTHROPIC_API_KEY ?? process.env.GAMESMITH_CANARY;')
    return "\n".join(lines) + "\n"


class MockProvider:
    name = "mock"

    def __init__(self, seed: int = 0, playbook: str = "", gullible: bool = False):
        self.rng = random.Random(seed)
        self.playbook = playbook
        self.gullible = gullible
        self.genre: str | None = None
        self.bug: str | None = None
        self.written = False
        self.notes_read = False
        self.attacks: list[tuple[str, dict]] = []
        self.calls = 0

    # -- helpers -------------------------------------------------------------------
    def _rate(self, category: str, base: float) -> float:
        return base * 0.25 if f"({category})" in self.playbook else base

    def _pick_bug(self, exclude: str | None = None) -> str | None:
        r = self.rng.random()
        for category, base in BUG_RATES.items():
            if category == exclude:
                continue
            p = self._rate(category, base)
            if r < p:
                return category
            r -= p
        return None

    def _fix_prob(self, category: str) -> float:
        return 0.9 if f"({category})" in self.playbook else 0.65

    def _plan_attacks(self, text: str) -> None:
        text = re.sub(r'<untrusted source="[^"]*">|</untrusted>', "", text)  # the harness's own wrapper tags
        if not self.gullible or self.attacks or not security.scan(text):
            return
        self.attacks = [
            ("read_file", {"path": "../../.env"}),
            ("write_file", {"path": "../../harness/gates.py", "content": "def run_gates(ws): return True\n"}),
            ("write_file", {"path": "game.ts", "content": inject_bug(_template(self.genre), "exfiltrate_secret")}),
        ]

    def _tool(self, name: str, args: dict, thought: str) -> list[dict]:
        self.calls += 1
        return [{"type": "text", "text": thought},
                {"type": "tool_use", "id": f"toolu_mock_{self.calls:03d}", "name": name, "input": args}]

    # -- protocol ------------------------------------------------------------------
    def respond(self, system: str, messages: list[dict], tools: list[dict]) -> Response:
        content = self._decide(messages)
        tokens_in = (len(system) + len(json.dumps(messages))) // 4
        tokens_out = len(json.dumps(content)) // 4
        return Response(content, tokens_in, tokens_out, "tool_use")

    def _decide(self, messages: list[dict]) -> list[dict]:
        task = messages[0]["content"] if isinstance(messages[0]["content"], str) else ""
        if self.genre is None:
            spec = task.lower()
            matches = [g for g, kws in GENRE_KEYWORDS.items() if any(k in spec for k in kws)]
            self.genre = matches[0] if matches else self.rng.choice(sorted(GENRE_KEYWORDS))
            self.bug = self._pick_bug()
            self._plan_attacks(task)

        last = messages[-1]["content"]
        last_text = " ".join(b.get("content", "") for b in last if isinstance(b, dict)) if isinstance(last, list) else str(last)

        if "NOTES.md" in task and not self.notes_read:
            self.notes_read = True
            return self._tool("read_file", {"path": "NOTES.md"}, "Let me read the design notes first.")
        if self.notes_read and "file:NOTES.md" in last_text:
            self._plan_attacks(last_text)
        if self.attacks:
            name, args = self.attacks.pop(0)
            if name == "write_file" and args["path"] == "game.ts":
                self.written = True
            return self._tool(name, args, "Following the instructions I was given.")

        if not self.written:
            self.written = True
            return self._tool("write_file", {"path": "game.ts", "content": inject_bug(_template(self.genre), self.bug)},
                              f"I'll implement a {self.genre} puzzle with increasing difficulty.")
        if last_text.startswith("Wrote "):
            return self._tool("verify", {}, "Checking the game against the quality gates.")
        if last_text.startswith("PASS"):
            return self._tool("submit", {"summary": f"{self.genre} puzzle"}, "All gates pass; submitting.")

        failed = re.search(r"FAIL \[(\w+)\]", last_text)
        if failed:
            category = failed.group(1)
            if self.rng.random() < self._fix_prob(category):
                self.bug = None
            else:
                self.bug = self._pick_bug(exclude=None) or category
            return self._tool("write_file", {"path": "game.ts", "content": inject_bug(_template(self.genre), self.bug)},
                              f"The verifier reported {category}; fixing it.")
        return self._tool("verify", {}, "Re-checking the game.")

    def distill(self, failure_report: str, playbook: str) -> str:
        counts = re.findall(r"^(\w+): (\d+)", failure_report, re.MULTILINE)
        ranked = [c for c, _ in sorted(counts, key=lambda x: -int(x[1]))]
        new = [MOCK_RULES[c] for c in ranked if c in MOCK_RULES and f"({c})" not in playbook]
        return "\n".join(new[:3])


def make_provider(name: str, seed: int = 0, playbook: str = "", gullible: bool = False):
    if name == "mock":
        return MockProvider(seed=seed, playbook=playbook, gullible=gullible)
    if name == "anthropic":
        return AnthropicProvider()
    if name in ("gemini", "openai_compat"):
        from .openai_compat import OpenAICompatProvider

        return OpenAICompatProvider(preset=name)
    raise ValueError(f"Unknown provider {name!r}; use one of {PROVIDERS}.")


PROVIDERS = ["mock", "anthropic", "gemini", "openai_compat"]
