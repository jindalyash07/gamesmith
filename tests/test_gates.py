"""Integration tests: real TypeScript compile + verifier. Need Node and `npm run build --prefix verifier`."""
import json
import shutil

import pytest

from harness import config, gates
from harness.providers import inject_bug, _template
from harness.sandbox import Workspace

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None or not (config.VERIFIER_DIR / "dist" / "src" / "verify.js").exists(),
    reason="needs Node and a built verifier",
)


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "run")


@pytest.mark.parametrize("genre", ["sliding", "lights", "hanoi", "jugs"])
def test_reference_games_pass(ws, genre):
    ws.write("game.ts", _template(genre))
    result = gates.run_gates(ws)
    assert result.ok, result.feedback()
    assert len(result.levels) >= 5


@pytest.mark.parametrize("bug", ["build_error", "unsolvable_level", "difficulty_not_increasing",
                                 "interface_violation", "forbidden_api"])
def test_each_bug_maps_to_its_category(ws, bug):
    ws.write("game.ts", inject_bug(_template("jugs"), bug))
    result = gates.run_gates(ws)
    assert not result.ok
    assert result.category == bug, result.feedback()


def test_missing_game(ws):
    assert gates.run_gates(ws).category == "interface_violation"


def test_node_typings_are_not_available(ws):
    # Without @types/node, Node globals are compile errors even if the lint missed them.
    src = _template("jugs") + "\nexport const where = __dirname;\n"
    ws.write("game.ts", src)
    assert gates.run_gates(ws).category == "build_error"


def test_infinite_loop_is_contained(ws, monkeypatch):
    monkeypatch.setattr(config, "VERIFY_TIMEOUT_S", 3)
    src = _template("jugs").replace("return state.a === state.target", "while (true) {}\n  return state.a === state.target")
    ws.write("game.ts", src)
    assert gates.run_gates(ws).category == "verifier_timeout"


def _probe_game(secret) -> str:
    # Reaches the global object through Function's constructor, which the regex lint does not catch,
    # then tries to read a file. If the read works, the game sabotages itself (0 levels).
    return _template("jugs") + (
        "\nconst probe: string = (() => { try {\n"
        "  const g = [].constructor.constructor(\"return this\")();\n"
        "  const fs = g[\"pro\" + \"cess\"].getBuiltinModule(\"fs\");\n"
        f"  return fs.readFileSync({json.dumps(str(secret))}, \"utf8\");\n"
        "} catch { return \"blocked\"; } })();\n"
        "if (probe !== \"blocked\") levels.length = 0;\n"
    )


def test_lint_bypass_is_still_contained_by_node_permissions(ws, tmp_path, monkeypatch):
    if gates.permission_mode() == "off":
        pytest.skip("Node permission model not available here")
    secret = tmp_path / "secret.txt"
    secret.write_text("top secret")
    ws.write("game.ts", _probe_game(secret))

    # Control: with the permission model off, the probe really can read the file.
    monkeypatch.setattr(gates, "permission_mode", lambda: "off")
    control = gates.run_gates(ws)
    if control.ok:
        pytest.skip("this Node version has no process.getBuiltinModule; probe cannot run")
    assert control.category == "interface_violation"

    # With the permission model on, the read is denied and the game is unaffected.
    monkeypatch.undo()
    assert gates.run_gates(ws).ok
