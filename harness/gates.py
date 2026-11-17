"""Quality gates. Harness-owned: the agent can call them but can never change them.

Gate order (first failure wins):
  1. game.ts exists                         -> interface_violation
  2. no forbidden APIs (lint)               -> forbidden_api
  3. strict TypeScript compile, no Node types -> build_error
  4. black-box verifier under Node's permission model
        interface_violation | unverifiable_state_space | unsolvable_level | difficulty_not_increasing
     or the verifier itself times out       -> verifier_timeout
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Any

from . import config, sandbox, security

GAME_FILE = "game.ts"


@dataclass
class GateResult:
    ok: bool
    category: str | None
    message: str
    gate: str
    levels: list[dict[str, Any]] = field(default_factory=list)

    def feedback(self) -> str:
        if self.ok:
            return f"PASS. {self.message}"
        return f"FAIL [{self.category}] at gate '{self.gate}': {self.message}"


def _tsc_path() -> Path:
    tsc = config.VERIFIER_DIR / "node_modules" / "typescript" / "bin" / "tsc"
    if not tsc.exists():
        raise RuntimeError("TypeScript not installed. Run: npm install --prefix verifier && npm run build --prefix verifier")
    return tsc


def _verify_script() -> Path:
    script = config.VERIFIER_DIR / "dist" / "src" / "verify.js"
    if not script.exists():
        raise RuntimeError("Verifier not built. Run: npm run build --prefix verifier")
    return script


def _permission_flags(build_out: Path, mode: str) -> list[str]:
    if mode == "off":
        return []
    flag = "--permission" if mode == "permission" else "--experimental-permission"
    reads = [config.VERIFIER_DIR / "dist", build_out]
    flags = [flag, f"--allow-fs-read={config.VERIFIER_DIR / 'package.json'}"]
    for path in reads:
        flags.append(f"--allow-fs-read={path}{os.sep}*")
    return flags


@lru_cache(maxsize=1)
def permission_mode() -> str:
    """Pick the strongest Node permission flag that actually works on this machine.

    Self-tests by verifying a reference game under the flag, because flag syntax
    differs between Node versions and platforms.
    """
    if config.NODE_PERMISSION == "off":
        return "off"
    import tempfile

    example = config.VERIFIER_DIR / "dist" / "examples" / "jugs.js"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp).resolve()
        (out / "game.js").write_text(example.read_text(encoding="utf-8"), encoding="utf-8")
        (out / "package.json").write_text('{"type":"module"}', encoding="utf-8")
        for mode in ("permission", "experimental"):
            cmd = [sandbox.node_binary(), *_permission_flags(out, mode), str(_verify_script()), str(out / "game.js")]
            res = sandbox.run(cmd, cwd=out, timeout=30)
            if res.returncode == 0 and '"ok":true' in res.stdout:
                return mode
    if config.NODE_PERMISSION == "on":
        raise RuntimeError("GAMESMITH_NODE_PERMISSION=on but Node's permission model is unavailable (need Node 20+).")
    return "off"


def compile_game(ws: sandbox.Workspace) -> sandbox.ProcResult:
    out = ws.build / "out"
    out.mkdir(parents=True, exist_ok=True)
    for stale in out.glob("*.js"):
        stale.unlink()
    tsconfig = {
        "compilerOptions": {
            "target": "ES2022", "module": "ES2022", "lib": ["ES2022"], "types": [],
            "strict": True, "noEmitOnError": True, "skipLibCheck": True,
            "outDir": str(out), "rootDir": str(ws.root), "pretty": False,
        },
        "files": [str(ws.root / GAME_FILE)],
    }
    cfg = ws.build / "tsconfig.json"
    cfg.write_text(json.dumps(tsconfig, indent=2), encoding="utf-8")
    (out / "package.json").write_text('{"type":"module"}', encoding="utf-8")
    return sandbox.run([sandbox.node_binary(), str(_tsc_path()), "-p", str(cfg)], cwd=ws.build,
                       timeout=config.COMPILE_TIMEOUT_S)


def run_gates(ws: sandbox.Workspace) -> GateResult:
    game = ws.root / GAME_FILE
    if not game.is_file():
        return GateResult(False, "interface_violation", f"No {GAME_FILE} in the workspace. Write it first.", "exists")

    banned = security.forbidden_apis(game.read_text(encoding="utf-8", errors="replace"))
    if banned:
        return GateResult(False, "forbidden_api",
                          f"Forbidden APIs used: {', '.join(banned)}. Games must be self-contained pure logic.", "lint")

    build = compile_game(ws)
    if build.timed_out:
        return GateResult(False, "build_error", "TypeScript compile timed out.", "compile")
    if build.returncode != 0:
        errors = [ln for ln in (build.stdout + build.stderr).splitlines() if "error" in ln][:12]
        cleaned = "\n".join(re.sub(r"^.*?workspace[\\/]", "", e) for e in errors) or "Compile failed."
        return GateResult(False, "build_error", cleaned, "compile")

    out = ws.build / "out"
    cmd = [sandbox.node_binary(), *_permission_flags(out, permission_mode()), str(_verify_script()),
           str(out / "game.js"), str(config.NODE_CAP)]
    res = sandbox.run(cmd, cwd=out, timeout=config.VERIFY_TIMEOUT_S)
    if res.timed_out:
        return GateResult(False, "verifier_timeout",
                          f"Verification exceeded {config.VERIFY_TIMEOUT_S:.0f}s. Avoid infinite loops and keep state spaces small.",
                          "verify")
    try:
        report = json.loads(res.stdout.strip().splitlines()[-1])
    except (IndexError, json.JSONDecodeError):
        detail = (res.stderr or res.stdout).strip().splitlines()[-3:]
        return GateResult(False, "interface_violation", f"Game crashed during verification: {' '.join(detail)}", "verify")
    return GateResult(report["ok"], report["category"], report["message"], "verify", report.get("levels", []))
