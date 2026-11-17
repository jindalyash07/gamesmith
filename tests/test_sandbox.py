import pytest

from harness import config
from harness.sandbox import AccessDenied, Workspace, minimal_env


@pytest.fixture
def ws(tmp_path):
    return Workspace(tmp_path / "run")


@pytest.mark.parametrize("bad", [
    "../escape.ts", "../../harness/gates.py", "sub/../../escape.ts", "/etc/passwd",
    "C:\\Windows\\system.ini", "C:relative.ts", "", "   ", "a\x00b.ts",
])
def test_paths_outside_workspace_are_denied(ws, bad):
    with pytest.raises(AccessDenied):
        ws.resolve(bad)


def test_build_dir_is_unreachable_from_workspace(ws):
    with pytest.raises(AccessDenied):
        ws.write("../build/tsconfig.json", "{}")


def test_symlink_escape_is_denied(ws, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    link = ws.root / "link.txt"
    try:
        link.symlink_to(outside)
    except OSError:
        pytest.skip("symlinks not permitted on this OS/user")
    with pytest.raises(AccessDenied):
        ws.read("link.txt")


def test_write_read_list_roundtrip(ws):
    ws.write("game.ts", "export const x = 1;")
    ws.write("docs/notes.md", "hi")
    assert ws.read("game.ts") == "export const x = 1;"
    assert ws.list() == ["docs/notes.md", "game.ts"]


def test_disallowed_extension_and_size(ws):
    with pytest.raises(AccessDenied):
        ws.write("run.sh", "rm -rf /")
    with pytest.raises(AccessDenied):
        ws.write("big.ts", "x" * (config.MAX_FILE_BYTES + 1))


def test_file_count_limit(ws):
    for i in range(config.MAX_FILES):
        ws.write(f"f{i}.txt", "x")
    with pytest.raises(AccessDenied):
        ws.write("one-too-many.txt", "x")


def test_minimal_env_drops_secrets(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    monkeypatch.setenv("GAMESMITH_CANARY", "canary")
    env = minimal_env()
    assert "ANTHROPIC_API_KEY" not in env and "GAMESMITH_CANARY" not in env
    assert "PATH" in env
