"""OpenAI-compatible provider (Gemini) tested against a fake HTTP server; no network or real key needed."""
import json

import httpx
import pytest

from harness.openai_compat import OpenAICompatProvider, to_openai_messages, from_openai_message
from harness.providers import ProviderError
from harness.tools import TOOL_SPECS


@pytest.fixture(autouse=True)
def fake_key(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setattr("time.sleep", lambda s: None)  # don't actually wait during retry tests


def provider_with(handler, **kw):
    return OpenAICompatProvider("gemini", transport=httpx.MockTransport(handler), **kw)


def tool_call_reply(name="write_file", args=None, call_id="call_1", signature="sig-abc"):
    return {
        "choices": [{"finish_reason": "tool_calls", "message": {
            "role": "assistant", "content": "Writing the game.",
            "tool_calls": [{"id": call_id, "type": "function",
                            "function": {"name": name, "arguments": json.dumps(args or {"path": "game.ts", "content": "x"})},
                            "extra_content": {"google": {"thought_signature": signature}}}],
        }}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 30},
    }


def test_request_format_and_response_parsing():
    seen = {}

    def handler(request):
        seen["url"] = str(request.url)
        seen["auth"] = request.headers["authorization"]
        seen["body"] = json.loads(request.content)
        return httpx.Response(200, json=tool_call_reply())

    p = provider_with(handler)
    resp = p.respond("SYSTEM", [{"role": "user", "content": "build hanoi"}], TOOL_SPECS)

    assert seen["url"].endswith("/v1beta/openai/chat/completions")
    assert seen["auth"] == "Bearer test-key"
    assert seen["body"]["messages"][0] == {"role": "system", "content": "SYSTEM"}
    assert seen["body"]["reasoning_effort"] == "low"  # thinking must not eat the output budget
    assert seen["body"]["max_tokens"] >= 16_000
    assert {t["function"]["name"] for t in seen["body"]["tools"]} == {t["name"] for t in TOOL_SPECS}
    assert resp.tokens_in == 120 and resp.tokens_out == 30
    tool_use = [b for b in resp.content if b["type"] == "tool_use"][0]
    assert tool_use["name"] == "write_file" and tool_use["input"]["path"] == "game.ts"


def test_thought_signature_is_sent_back_unchanged():
    blocks = from_openai_message(tool_call_reply()["choices"][0]["message"], step=1)
    history = [
        {"role": "user", "content": "build hanoi"},
        {"role": "assistant", "content": blocks},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "call_1", "content": "Wrote game.ts", "is_error": False}]},
    ]
    msgs = to_openai_messages("SYS", history)
    assert msgs[2]["tool_calls"][0]["extra_content"]["google"]["thought_signature"] == "sig-abc"
    assert msgs[3] == {"role": "tool", "tool_call_id": "call_1", "content": "Wrote game.ts"}


def test_missing_call_ids_and_bad_json_are_handled():
    message = {"tool_calls": [{"type": "function", "function": {"name": "verify", "arguments": "{not json"}}]}
    blocks = from_openai_message(message, step=4)
    assert blocks[0]["id"] == "call_4_0" and blocks[0]["input"] == {}


def test_retries_on_rate_limit_then_succeeds():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "1"}, json={"error": "slow down"})
        return httpx.Response(200, json=tool_call_reply())

    resp = provider_with(handler).respond("S", [{"role": "user", "content": "x"}], TOOL_SPECS)
    assert calls["n"] == 3 and resp.content


def test_gives_up_with_provider_error():
    p = provider_with(lambda r: httpx.Response(503, text="overloaded"), max_attempts=2)
    with pytest.raises(ProviderError):
        p.respond("S", [{"role": "user", "content": "x"}], TOOL_SPECS)


def test_non_retryable_error_fails_fast():
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        return httpx.Response(400, text="bad model name")

    with pytest.raises(ProviderError, match="400"):
        provider_with(handler).respond("S", [{"role": "user", "content": "x"}], TOOL_SPECS)
    assert calls["n"] == 1


def test_missing_key_is_a_clear_error(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY")
    with pytest.raises(ProviderError, match="GEMINI_API_KEY"):
        OpenAICompatProvider("gemini")


def test_free_tier_cost_defaults_to_zero():
    p = provider_with(lambda r: httpx.Response(200, json=tool_call_reply()))
    assert p.price_in == 0 and p.price_out == 0
