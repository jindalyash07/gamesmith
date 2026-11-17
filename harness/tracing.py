"""Structured JSONL tracing: one event per LLM call, tool call, gate result and security signal.

Traces are the raw material for metrics.py (observability) and improve.py (self-improvement).
"""
from __future__ import annotations

import json
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator


class Tracer:
    def __init__(self, run_id: str, path: Path):
        self.run_id = run_id
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.step = 0
        self.events: list[dict[str, Any]] = []

    def event(self, type_: str, **fields: Any) -> dict[str, Any]:
        record = {"ts": round(time.time(), 3), "run_id": self.run_id, "step": self.step, "type": type_, **fields}
        self.events.append(record)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(record, default=str) + "\n")
        return record

    @contextmanager
    def span(self, type_: str, **fields: Any) -> Iterator[dict[str, Any]]:
        """Time a block; callers can add result fields to the yielded dict."""
        extra: dict[str, Any] = {}
        start = time.perf_counter()
        try:
            yield extra
        except Exception as exc:
            self.event(type_, duration_ms=round((time.perf_counter() - start) * 1000), ok=False,
                       error=f"{type(exc).__name__}: {exc}", **fields, **extra)
            raise
        self.event(type_, duration_ms=round((time.perf_counter() - start) * 1000),
                   **{"ok": True, **fields, **extra})


def load_trace(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]
