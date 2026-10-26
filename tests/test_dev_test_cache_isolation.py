"""Test entrypoints must not read or overwrite the caller's cache assets."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

import pytest

from gametool import dev_test

_REPO = Path(__file__).resolve().parents[1]
_PROBE = """
import json, os, subprocess, sys
from pathlib import Path
from gametool.cache_root import gamexray_cache_root
from gametool import pack_query_cli as queries, gui_pack_query as gui
from gametool.gui_export_actions import save_last_pack_dir

observed = {"collection_root": str(gamexray_cache_root())}
queries._store_last_query(Path("validation-pack"), "stats", "")
Path(os.environ["GAMEXRAY_PROBE_RESULT"]).write_text(json.dumps(observed), encoding="utf-8")
if os.environ["GAMEXRAY_PROBE_MODE"] == "collection-fail":
    raise RuntimeError("controlled collection failure")

def test_write_runtime_assets():
    gui._HISTORY[:] = [("stats", "")]
    gui._PINNED[:] = [("validation", "temporary text")]
    gui._WINDOW_GEOMETRY.clear()
    gui._WINDOW_GEOMETRY["validation"] = "520x360"
    gui._save_memo()
    save_last_pack_dir("validation-pack")
    observed["test_root"] = str(gamexray_cache_root())
    child = subprocess.run([sys.executable, "-c", "from gametool.cache_root import gamexray_cache_root; print(gamexray_cache_root())"], check=True, capture_output=True, encoding="utf-8")
    observed["child_root"] = child.stdout.strip()
    Path(os.environ["GAMEXRAY_PROBE_RESULT"]).write_text(json.dumps(observed), encoding="utf-8")
    assert os.environ["GAMEXRAY_PROBE_MODE"] != "test-fail", "controlled test failure"
"""
_IN_PROCESS = """
import json, os, sys
from pathlib import Path
import pytest
out = []
for _ in range(int(os.environ.get("GAMEXRAY_PROBE_RUNS", "1"))):
    before = {"present": "GAMEXRAY_CACHE_DIR" in os.environ, "value": os.environ.get("GAMEXRAY_CACHE_DIR")}
    code = pytest.main(sys.argv[1:])
    after = {"present": "GAMEXRAY_CACHE_DIR" in os.environ, "value": os.environ.get("GAMEXRAY_CACHE_DIR")}
    probe = Path(os.environ["GAMEXRAY_PROBE_RESULT"])
    out.append({"before": before, "after": after, "code": code, "probe": json.loads(probe.read_text()) if probe.exists() else None})
Path(os.environ["GAMEXRAY_PROBE_SESSION_RESULT"]).write_text(json.dumps(out), encoding="utf-8")
raise SystemExit(code)
"""


def _snapshot(root: Path) -> dict[str, tuple[int, int, str]]:
    return {
        path.relative_to(root).as_posix(): (
            path.stat().st_size,
            path.stat().st_mtime_ns,
            hashlib.sha256(path.read_bytes()).hexdigest(),
        )
        for path in root.rglob("*")
        if path.is_file()
    }


def _prepare(
    tmp_path: Path,
    *,
    mode: str = "pass",
    original: str = "explicit",
    guard: bool = False,
) -> tuple[Path, dict[str, str], Path]:
    suite = tmp_path / "suite"
    suite.mkdir()
    temp_base = tmp_path / "temporary"
    temp_base.mkdir()
    profile = tmp_path / "profile"
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONPATH"] = str(_REPO) + os.pathsep + env.get("PYTHONPATH", "")
    env["LOCALAPPDATA"] = str(profile)
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(temp_base)
    if original == "explicit":
        caller = tmp_path / "用户缓存"
        env["GAMEXRAY_CACHE_DIR"] = str(caller)
    else:
        caller = (
            profile / "gamexray" / "cache"
            if sys.platform == "win32"
            else temp_base / "gamexray-cache"
        )
        if original == "empty":
            env["GAMEXRAY_CACHE_DIR"] = ""
        else:
            env.pop("GAMEXRAY_CACHE_DIR", None)
    assets = {
        "gui-query-memo/history.json": '[["item", "原始关键词"]]',
        "gui-query-memo/pinned.json": '[["原始收藏", "完整正文"]]',
        "gui-query-memo/geometry.json": '{"原始窗口":"900x700+1+2"}',
        "gui-query-memo/pack-query-last.json": '{"pack":"original-pack","command":"item","query":"原始关键词"}',
        "gui-last-pack.txt": "original-pack",
    }
    for name, value in assets.items():
        path = caller / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")
    (suite / "test_probe.py").write_text(_PROBE, encoding="utf-8")
    (suite / "pytest.ini").write_text("[pytest]\n", encoding="utf-8")
    if guard and (_REPO / "conftest.py").is_file():
        shutil.copyfile(_REPO / "conftest.py", suite / "conftest.py")
    env["GAMEXRAY_PROBE_RESULT"] = str(tmp_path / "observed.json")
    env["GAMEXRAY_PROBE_SESSION_RESULT"] = str(tmp_path / "session.json")
    env["GAMEXRAY_PROBE_MODE"] = mode
    return suite, env, caller


def _pytest_args(suite: Path) -> list[str]:
    return [
        "-q",
        "-c",
        str(suite / "pytest.ini"),
        "--confcutdir",
        str(suite),
        str(suite / "test_probe.py"),
    ]


def _assert_private(probe: dict[str, str], caller: Path) -> None:
    for value in probe.values():
        assert Path(value).is_absolute()
        root = Path(value).resolve()
        assert root != caller.resolve()
        assert not root.is_relative_to(caller.resolve())
        assert not root.is_relative_to(_REPO)
    if "test_root" in probe:
        assert probe["child_root"] == probe["test_root"]


@pytest.mark.parametrize(
    "mode,code", [("pass", 0), ("test-fail", 1), ("collection-fail", 2)]
)
def test_test_runner_protects_caller_assets_before_collection(
    tmp_path: Path, mode: str, code: int
) -> None:
    suite, env, caller = _prepare(tmp_path, mode=mode)
    before = _snapshot(caller)
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "gametool.dev_test",
            "--noconftest",
            *_pytest_args(suite),
        ],
        cwd=_REPO,
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == code, result.stdout + result.stderr
    assert _snapshot(caller) == before
    probe = json.loads(Path(env["GAMEXRAY_PROBE_RESULT"]).read_text())
    if mode != "collection-fail":
        assert "test_root" in probe and "child_root" in probe
    if mode != "pass":
        assert "controlled " in result.stdout
    _assert_private(probe, caller)


@pytest.mark.parametrize("original", ["explicit", "unset", "empty"])
def test_direct_pytest_isolates_collection_and_restores_caller_environment(
    tmp_path: Path, original: str
) -> None:
    suite, env, caller = _prepare(tmp_path, original=original, guard=True)
    before = _snapshot(caller)
    result = subprocess.run(
        [sys.executable, "-c", _IN_PROCESS, *_pytest_args(suite)],
        cwd=suite,
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _snapshot(caller) == before
    session = json.loads(Path(env["GAMEXRAY_PROBE_SESSION_RESULT"]).read_text())[0]
    assert session["after"] == session["before"]
    assert "test_root" in session["probe"] and "child_root" in session["probe"]
    _assert_private(session["probe"], caller)


@pytest.mark.parametrize("mode,code", [("test-fail", 1), ("collection-fail", 2)])
def test_direct_pytest_failure_keeps_assets_and_environment(
    tmp_path: Path, mode: str, code: int
) -> None:
    suite, env, caller = _prepare(tmp_path, mode=mode, guard=True)
    before = _snapshot(caller)
    result = subprocess.run(
        [sys.executable, "-c", _IN_PROCESS, *_pytest_args(suite)],
        cwd=suite,
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == code, result.stdout + result.stderr
    assert "controlled " in result.stdout
    assert _snapshot(caller) == before
    session = json.loads(Path(env["GAMEXRAY_PROBE_SESSION_RESULT"]).read_text())[0]
    assert session["after"] == session["before"]
    if mode != "collection-fail":
        assert "test_root" in session["probe"] and "child_root" in session["probe"]
    _assert_private(session["probe"], caller)


def test_repeated_pytest_sessions_get_distinct_caches(tmp_path: Path) -> None:
    suite, env, caller = _prepare(tmp_path, guard=True)
    env["GAMEXRAY_PROBE_RUNS"] = "2"
    before = _snapshot(caller)
    result = subprocess.run(
        [sys.executable, "-c", _IN_PROCESS, *_pytest_args(suite)],
        cwd=suite,
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert _snapshot(caller) == before
    sessions = json.loads(Path(env["GAMEXRAY_PROBE_SESSION_RESULT"]).read_text())
    assert len(sessions) == 2
    assert sessions[0]["probe"]["test_root"] != sessions[1]["probe"]["test_root"]
    assert all(session["after"] == session["before"] for session in sessions)


def test_runner_function_does_not_mutate_its_parent_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capfd: pytest.CaptureFixture[str]
) -> None:
    suite, env, caller = _prepare(tmp_path)
    for key, value in env.items():
        if key.startswith("GAMEXRAY_") or key == "PYTHONPATH":
            monkeypatch.setenv(key, value)
    before = _snapshot(caller)
    assert dev_test.main(["--noconftest", *_pytest_args(suite)]) == 0
    capfd.readouterr()
    assert os.environ["GAMEXRAY_CACHE_DIR"] == str(caller)
    assert _snapshot(caller) == before


@pytest.mark.parametrize("failure", ["allocation", "repository", "caller-cache"])
def test_runner_does_not_launch_pytest_when_isolation_is_unavailable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    failure: str,
) -> None:
    caller = tmp_path / "caller"
    caller.mkdir()
    monkeypatch.setenv("GAMEXRAY_CACHE_DIR", str(caller))
    marker = tmp_path / "launched.txt"

    def launched(command, **_kwargs):
        marker.write_text("unsafe child started")
        return subprocess.CompletedProcess(command, 0)

    def no_space(**_kwargs):
        raise PermissionError("controlled cache allocation failure")

    def harmless_allocation(**_kwargs):
        # A broken path guard must fail without creating files in the repo.
        isolated = tmp_path / "would-allocate-cache"
        isolated.mkdir()
        return str(isolated)

    monkeypatch.setattr(dev_test.subprocess, "run", launched)
    if failure == "allocation":
        monkeypatch.setattr(tempfile, "mkdtemp", no_space)
    else:
        monkeypatch.setattr(tempfile, "mkdtemp", harmless_allocation)
        monkeypatch.setattr(
            tempfile,
            "gettempdir",
            lambda: str(_REPO if failure == "repository" else caller),
        )
    assert dev_test.main(["--version"]) == 2
    assert not marker.exists()
    assert "隔离" in capsys.readouterr().err
    assert os.environ["GAMEXRAY_CACHE_DIR"] == str(caller)


def test_direct_pytest_refuses_a_cache_inside_caller_assets(tmp_path: Path) -> None:
    suite, env, caller = _prepare(tmp_path, guard=True)
    for key in ("TMPDIR", "TEMP", "TMP"):
        env[key] = str(caller)
    before = _snapshot(caller)
    result = subprocess.run(
        [sys.executable, "-c", _IN_PROCESS, *_pytest_args(suite)],
        cwd=suite,
        env=env,
        capture_output=True,
        encoding="utf-8",
    )
    assert result.returncode == 4, result.stdout + result.stderr
    assert _snapshot(caller) == before
    session = json.loads(Path(env["GAMEXRAY_PROBE_SESSION_RESULT"]).read_text())[0]
    assert session["after"] == session["before"] and session["probe"] is None
