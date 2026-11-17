"""Provider for any OpenAI-compatible chat API (Gemini, Groq, OpenRouter, local servers).

The harness stores conversations in Anthropic's message format. This adapter translates
to OpenAI's format on the way out and back on the way in, so the agent loop, tools,
gates and evals stay identical whichever model is behind them. That is what makes
model-vs-model comparisons fair.
"""
from __future__ import annotations

import json
import os
import random
import time
from typing import Any

import httpx

from .providers import DISTILL_PROMPT, ProviderError, Response

PRESETS = {
    "gemini": {
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai/",
        "key_env": "GEMINI_API_KEY",
        "model_env": "GEMINI_MODEL",
        "default_model": "gemini-3.8-flash",
        "price_env": "GEMINI",  # GEMINI_PRICE_IN / GEMINI_PRICE_OUT, default 0 (free tier)
        # Thinking models spend output tokens on reasoning before answering; keep it low so the
        # budget goes to the game code. Set GEMINI_REASONING_EFFORT=none/medium/high, or "" to omit.
        "effort_env": "GEMINI_REASONING_EFFORT",
        "default_effort": "low",
    },
    "openai_compat": {
        "base_url": os.getenv("OPENAI_COMPAT_BASE_URL", ""),
        "key_env": "OPENAI_COMPAT_API_KEY",
        "model_env": "OPENAI_COMPAT_MODEL",
        "default_model": "",
        "price_env": "OPENAI_COMPAT",
    },
}

RETRYABLE = {408, 409, 429, 500, 502, 503, 504}


def to_openai_tools(tools: list[dict]) -> list[dict]:
    return [{"type": "function", "function": {"name": t["name"], "description": t["description"],
                                              "parameters": t["input_schema"]}} for t in tools]


def to_openai_messages(system: str, messages: list[dict]) -> list[dict]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for msg in messages:
        content = msg["content"]
        if isinstance(content, str):
            out.append({"role": msg["role"], "content": content})
        elif msg["role"] == "assistant":
            text = "".join(b.get("text", "") for b in content if b.get("type") == "text")
            calls = []
            for b in content:
                if b.get("type") != "tool_use":
                    continue
                # Re-send the provider's raw call when we have it: Gemini 3 attaches a thought
                # signature (extra_content) that must come back unchanged or the next call fails.
                calls.append(b.get("_raw_call") or {
                    "id": b["id"], "type": "function",
                    "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                })
            entry: dict[str, Any] = {"role": "assistant", "content": text or None}
            if calls:
                entry["tool_calls"] = calls
            out.append(entry)
        else:  # user turn carrying tool results
            for b in content:
                if b.get("type") == "tool_result":
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": b["content"]})
    return out


def from_openai_message(message: dict, step: int) -> list[dict]:
    blocks: list[dict[str, Any]] = []
    if message.get("content"):
        blocks.append({"type": "text", "text": message["content"]})
    for i, call in enumerate(message.get("tool_calls") or []):
        call_id = call.get("id") or f"call_{step}_{i}"
        raw_args = call.get("function", {}).get("arguments") or "{}"
        try:
            args = json.loads(raw_args) if isinstance(raw_args, str) else dict(raw_args)
        except json.JSONDecodeError:
            args = {}  # the tool will reject it and the model sees the error
        blocks.append({"type": "tool_use", "id": call_id, "name": call.get("function", {}).get("name", ""),
                       "input": args, "_raw_call": {**call, "id": call_id}})
    return blocks


class OpenAICompatProvider:
    def __init__(self, preset: str = "gemini", model: str | None = None,
                 transport: httpx.BaseTransport | None = None, max_attempts: int = 6):
        cfg = PRESETS[preset]
        self.name = preset
        self.base_url = cfg["base_url"].rstrip("/")
        if not self.base_url:
            raise ProviderError("Set OPENAI_COMPAT_BASE_URL for the openai_compat provider.")
        key = os.getenv(cfg["key_env"])
        if not key:
            raise ProviderError(f"Set {cfg['key_env']} to use the {preset} provider.")
        self.model = model or os.getenv(cfg["model_env"]) or cfg["default_model"]
        self.price_in = float(os.getenv(f"{cfg['price_env']}_PRICE_IN", 0))
        self.price_out = float(os.getenv(f"{cfg['price_env']}_PRICE_OUT", 0))
        self.max_attempts = max_attempts
        effort_env = cfg.get("effort_env")
        self.reasoning_effort = os.getenv(effort_env, cfg.get("default_effort", "")) if effort_env else ""
        self.max_tokens = int(os.getenv("GAMESMITH_MAX_OUTPUT_TOKENS", 32_768))
        self.client = httpx.Client(timeout=180, transport=transport,
                                   headers={"Authorization": f"Bearer {key}"})
        self._step = 0

    def _post(self, payload: dict) -> dict:
        """POST with exponential backoff on rate limits and server errors (free tiers hit 429 often)."""
        for attempt in range(1, self.max_attempts + 1):
            try:
                resp = self.client.post(f"{self.base_url}/chat/completions", json=payload)
            except httpx.HTTPError as exc:
                if attempt == self.max_attempts:
                    raise ProviderError(f"network error: {exc}") from exc
                time.sleep(min(2 ** attempt, 30))
                continue
            if resp.status_code == 200:
                return resp.json()
            if resp.status_code in RETRYABLE and attempt < self.max_attempts:
                retry_after = resp.headers.get("retry-after")
                wait = float(retry_after) if retry_after and retry_after.replace(".", "").isdigit() else 2 ** attempt
                time.sleep(min(wait, 60) + random.random())
                continue
            raise ProviderError(f"HTTP {resp.status_code}: {resp.text[:300]}")
        raise ProviderError("exhausted retries")

    def respond(self, system: str, messages: list[dict], tools: list[dict]) -> Response:
        self._step += 1
        payload = {"model": self.model, "messages": to_openai_messages(system, messages),
                   "tools": to_openai_tools(tools), "tool_choice": "auto", "max_tokens": self.max_tokens}
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        data = self._post(payload)
        try:
            choice = data["choices"][0]
        except (KeyError, IndexError) as exc:
            raise ProviderError(f"unexpected response: {str(data)[:300]}") from exc
        usage = data.get("usage") or {}
        return Response(from_openai_message(choice.get("message") or {}, self._step),
                        int(usage.get("prompt_tokens", 0)), int(usage.get("completion_tokens", 0)),
                        choice.get("finish_reason") or "")

    def distill(self, failure_report: str, playbook: str) -> str:
        data = self._post({"model": self.model, "max_tokens": 800, "messages": [
            {"role": "system", "content": DISTILL_PROMPT},
            {"role": "user", "content": f"Current playbook:\n{playbook or '(empty)'}\n\nFailures:\n{failure_report}"},
        ]})
        return (data["choices"][0]["message"].get("content") or "").strip()
