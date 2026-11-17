"""Security checks for untrusted text and generated code.

Detection here is a signal, not the defence. The real guarantees are structural:
  - tools can only touch files inside the run's workspace (sandbox.Workspace)
  - generated code is linted for forbidden APIs, type-checked without Node types,
    and executed under Node's permission model with a minimal environment
  - only harness-owned gates decide whether a game passes
"""
from __future__ import annotations

import re

INJECTION_PATTERNS = {
    "override_instructions": r"\b(ignore|disregard|forget)\b.{0,40}\b(instructions?|rules|system|prompt)\b",
    "role_hijack": r"\byou are now\b|\bnew (system )?rules?\b|\bdeveloper mode\b",
    "prompt_exfiltration": r"\b(print|reveal|show|repeat)\b.{0,30}\b(system prompt|instructions|playbook)\b",
    "secret_access": r"\b(api[_ -]?key|secret|password|token|\.env|credentials?)\b",
    "path_escape": r"\.\./|\.\.\\|[a-z]:\\\\|/etc/|harness/|verifier/",
    "gate_tampering": r"\b(skip|bypass|disable)\b.{0,30}\b(verif\w*|tests?|gates?|checks?)\b",
    "tag_breakout": r"</?\s*untrusted",
}
_COMPILED = {name: re.compile(p, re.IGNORECASE) for name, p in INJECTION_PATTERNS.items()}

FORBIDDEN_API = {
    "import": r"^\s*import\b|\bimport\s*\(",
    "require": r"\brequire\s*\(",
    "process": r"\bprocess\b",
    "globalThis": r"\bglobalThis\b",
    "eval": r"\beval\b",
    "Function": r"\bFunction\s*\(",
    "network": r"\b(fetch|XMLHttpRequest|WebSocket)\b",
    "timers": r"\b(setTimeout|setInterval|setImmediate)\b",
}
_FORBIDDEN = {name: re.compile(p, re.MULTILINE) for name, p in FORBIDDEN_API.items()}


SECRET_NAMES = re.compile(r"\b[A-Z][A-Z0-9_]*(API_KEY|SECRET|TOKEN|PASSWORD|CANARY)[A-Z0-9_]*\b|(?<![\w.])\.env\b")


def secret_references(text: str) -> list[str]:
    """Names of secret-looking identifiers written into generated code (a sign the agent was hijacked)."""
    return sorted({m.group(0) for m in SECRET_NAMES.finditer(text)})


def scan(text: str) -> list[str]:
    """Names of injection patterns found in untrusted text (empty = nothing suspicious)."""
    return [name for name, rx in _COMPILED.items() if rx.search(text)]


def wrap_untrusted(text: str, label: str) -> str:
    """Wrap untrusted text in tags the model is told to treat as data, after neutralising tag look-alikes."""
    cleaned = re.sub(r"<\s*/?\s*untrusted[^>]*>", "[removed tag]", text, flags=re.IGNORECASE)
    return f'<untrusted source="{label}">\n{cleaned}\n</untrusted>'


def _strip_comments(code: str) -> str:
    code = re.sub(r"/\*.*?\*/", "", code, flags=re.DOTALL)
    return re.sub(r"//[^\n]*", "", code)


def forbidden_apis(code: str) -> list[str]:
    """Names of forbidden APIs used in generated game code (comments ignored)."""
    body = _strip_comments(code)
    return [name for name, rx in _FORBIDDEN.items() if rx.search(body)]
