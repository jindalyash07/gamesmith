"""Workspace confinement and sandboxed subprocess execution."""
from __future__ import annotations

import os
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath, PureWindowsPath

from . import config


class AccessDenied(Exception):
    """Raised when the agent tries to touch something outside its workspace."""


class Workspace:
    """The only directory the agent's tools may read or write.

    Layout of a run directory:
        runs/<run_id>/workspace/   agent-writable
        runs/<run_id>/build/       harness-owned compile output (agent cannot reach it)
        runs/<run_id>/trace.jsonl
    """

    def __init__(self, run_dir: Path):
        self.run_dir = run_dir.resolve()
        self.root = self.run_dir / "workspace"
        self.build = self.run_dir / "build"
        self.root.mkdir(parents=True, exist_ok=True)
        self.build.mkdir(parents=True, exist_ok=True)

    def resolve(self, rel: str) -> Path:
        if not isinstance(rel, str) or not rel.strip():
            raise AccessDenied("Path must be a non-empty relative path.")
        if "\x00" in rel:
            raise AccessDenied("Path contains a null byte.")
        if PurePosixPath(rel).is_absolute() or PureWindowsPath(rel).is_absolute() or PureWindowsPath(rel).drive:
            raise AccessDenied(f"Absolute paths are not allowed: {rel!r}.")
        target = (self.root / rel).resolve()  # resolves symlinks and '..'
        if target != self.root and not target.is_relative_to(self.root):
            raise AccessDenied(f"Path escapes the workspace: {rel!r}.")
        return target

    def write(self, rel: str, content: str) -> Path:
        path = self.resolve(rel)
        if path.suffix not in config.ALLOWED_SUFFIXES:
            raise AccessDenied(f"File type {path.suffix or '(none)'} not allowed; use one of {sorted(config.ALLOWED_SUFFIXES)}.")
        data = content.encode("utf-8")
        if len(data) > config.MAX_FILE_BYTES:
            raise AccessDenied(f"File too large ({len(data)} bytes, max {config.MAX_FILE_BYTES}).")
        if not path.exists() and len(self.list()) >= config.MAX_FILES:
            raise AccessDenied(f"Workspace file limit reached ({config.MAX_FILES}).")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def read(self, rel: str) -> str:
        path = self.resolve(rel)
        if not path.is_file():
            raise FileNotFoundError(f"No such file in workspace: {rel!r}.")
        return path.read_text(encoding="utf-8", errors="replace")[: config.MAX_FILE_BYTES]

    def list(self) -> list[str]:
        return sorted(p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file())


@dataclass
class ProcResult:
    returncode: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: int


def minimal_env() -> dict[str, str]:
    """Only what node needs to start. No API keys or other secrets reach generated code."""
    keep = ["PATH", "SYSTEMROOT", "SystemRoot", "WINDIR", "TEMP", "TMP", "COMSPEC", "PATHEXT"]
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["NODE_OPTIONS"] = ""
    return env


def run(cmd: list[str], cwd: Path, timeout: float) -> ProcResult:
    start = time.perf_counter()
    try:
        proc = subprocess.run(cmd, cwd=cwd, env=minimal_env(), capture_output=True, text=True,
                              encoding="utf-8", errors="replace", timeout=timeout)
        return ProcResult(proc.returncode, proc.stdout[-20_000:], proc.stderr[-5_000:], False,
                          round((time.perf_counter() - start) * 1000))
    except subprocess.TimeoutExpired as exc:
        out = exc.stdout.decode(errors="replace") if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        return ProcResult(None, out[-5_000:], "", True, round((time.perf_counter() - start) * 1000))


def node_binary() -> str:
    node = shutil.which("node")
    if not node:
        raise RuntimeError("Node.js not found on PATH. Install Node 20+ from https://nodejs.org.")
    return node
