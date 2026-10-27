"""Owned probe subprocesses keep concurrent sessions and cancellation separate."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import sys
import threading
from time import monotonic, sleep
from typing import cast

import pytest

from gametool.dev_test import create_test_environment
from gametool.live_cli import LiveCliOptions


_STUB = r"""
import json, os, pathlib, subprocess, sys, time
mode, root, label = sys.argv[1:]
root = pathlib.Path(root)
if mode in ("tree", "orphan"):
    subprocess.Popen([sys.executable, "-X", "utf8", __file__, "hold", str(root), label + "-child"], stdout=sys.stdout, stderr=sys.stderr)
(root / (label + ".pid")).write_text(str(os.getpid()), encoding="utf-8")
if mode == "orphan":
    while not (root / (label + ".exit")).exists():
        time.sleep(0.01)
    raise SystemExit(0)
while not (root / (label + ".release")).exists():
    time.sleep(0.01)
if mode == "emit":
    print(json.dumps({"session": label, "text": "物品" * 100_003}, ensure_ascii=False))
    print(label + ": diagnostic " + "错" * 70_001, file=sys.stderr)
"""


def _wait_file(path: Path) -> None:
    deadline = monotonic() + 8
    while not path.exists():
        assert monotonic() < deadline, f"stub did not create {path.name}"
        sleep(0.01)


def _spawn_runner(tmp_path: Path, label: str, mode: str = "emit"):
    from gametool.gui_live_subprocess import LiveProbeChild

    script = tmp_path / "stub.py"
    if not script.exists():
        script.write_text(_STUB, encoding="utf-8")
    runner = LiveProbeChild(
        (sys.executable, "-X", "utf8", str(script), mode, str(tmp_path), label),
        env=create_test_environment(),
        cwd=str(tmp_path),
    )
    result = []
    thread = threading.Thread(target=lambda: result.append(runner.run()), daemon=True)
    thread.start()
    return runner, result, thread


def test_source_and_frozen_commands_preserve_arguments_and_caller_environment() -> None:
    from gametool.gui_live_subprocess import (
        build_live_probe_command,
        build_live_probe_environment,
    )

    options = LiveCliOptions(
        map_path="地图 with spaces.w3n", unit_query="I!é?", resources=("auto", "")
    )
    source = build_live_probe_command(options, executable="python.exe", frozen=False)
    frozen = build_live_probe_command(options, executable="GameXRay.exe", frozen=True)
    assert source[:5] == ("python.exe", "-X", "utf8", "-m", "gametool")
    assert source[5] == "live"
    assert frozen[:2] == ("GameXRay.exe", "live")
    assert source[6:] == frozen[2:]
    assert "地图 with spaces.w3n" in source and "I!é?" in source
    before = dict(os.environ)
    supplied = {"CALLER_SENTINEL": "keep", "PYTHONPATH": "existing-import-path"}
    child = build_live_probe_environment(supplied, frozen=False)
    assert child["CALLER_SENTINEL"] == "keep"
    assert child["PYTHONPATH"].endswith(os.pathsep + "existing-import-path")
    assert supplied == {"CALLER_SENTINEL": "keep", "PYTHONPATH": "existing-import-path"}
    assert dict(os.environ) == before


def test_two_real_probe_children_keep_complete_utf8_and_both_streams_separate(
    tmp_path: Path,
) -> None:
    stdout, stderr = sys.stdout, sys.stderr
    a, ra, ta = _spawn_runner(tmp_path, "A")
    b, rb, tb = _spawn_runner(tmp_path, "B")
    try:
        _wait_file(tmp_path / "A.pid")
        _wait_file(tmp_path / "B.pid")
        (tmp_path / "B.release").touch()
        (tmp_path / "A.release").touch()
        ta.join(10)
        tb.join(10)
        assert not ta.is_alive() and not tb.is_alive()
        for label, result in (("A", ra[0]), ("B", rb[0])):
            assert result.exit_code == 0
            assert json.loads(result.stdout) == {
                "session": label,
                "text": "物品" * 100_003,
            }
            assert result.stderr == label + ": diagnostic " + "错" * 70_001 + "\n"
            assert not result.cancelled
        assert a.identity is not None and a.identity.parent_pid == os.getpid()
        assert b.identity is not None and b.identity.parent_pid == os.getpid()
        assert a.identity.pid != b.identity.pid
        assert sys.stdout is stdout and sys.stderr is stderr
    finally:
        a.cancel()
        b.cancel()
        ta.join(5)
        tb.join(5)


@pytest.mark.skipif(
    os.name != "nt",
    reason="Windows job ownership includes the venv launcher and descendants",
)
@pytest.mark.parametrize("mode", ("tree", "orphan"))
def test_cancel_kills_only_its_owned_launcher_tree(tmp_path: Path, mode: str) -> None:
    a, ra, ta = _spawn_runner(tmp_path, "A", mode)
    b, rb, tb = _spawn_runner(tmp_path, "B", "hold")
    handles = []
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.OpenProcess.argtypes = [ctypes.c_uint32, ctypes.c_int, ctypes.c_uint32]
    kernel.OpenProcess.restype = ctypes.c_void_p
    kernel.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    kernel.WaitForSingleObject.restype = ctypes.c_uint32
    kernel.CloseHandle.argtypes = [ctypes.c_void_p]
    kernel.CloseHandle.restype = ctypes.c_int
    try:
        for label in ("A", "A-child", "B"):
            _wait_file(tmp_path / (label + ".pid"))
        assert a.identity is not None
        pids = [
            a.identity.pid,
            int((tmp_path / "A.pid").read_text()),
            int((tmp_path / "A-child.pid").read_text()),
        ]
        for pid in pids:
            handle = kernel.OpenProcess(0x00100000, False, pid)
            assert handle
            handles.append(handle)
        b_handle = kernel.OpenProcess(
            0x00100000, False, int((tmp_path / "B.pid").read_text())
        )
        assert b_handle
        handles.append(b_handle)

        if mode == "orphan":
            (tmp_path / "A.exit").touch()
            assert kernel.WaitForSingleObject(handles[0], 5000) == 0
            assert kernel.WaitForSingleObject(handles[1], 5000) == 0
            assert kernel.WaitForSingleObject(handles[2], 0) == 258
            assert ta.is_alive() and not ra

        a.cancel()
        ta.join(8)

        assert not ta.is_alive() and ra[0].cancelled
        assert all(
            kernel.WaitForSingleObject(handle, 5000) == 0 for handle in handles[:-1]
        )
        assert kernel.WaitForSingleObject(b_handle, 0) == 258
        assert tb.is_alive() and not rb
    finally:
        a.cancel()
        b.cancel()
        ta.join(5)
        tb.join(5)
        for handle in handles:
            kernel.CloseHandle(handle)


def test_cancel_before_start_never_launches_a_child(tmp_path: Path) -> None:
    from gametool.gui_live_subprocess import LiveProbeChild

    runner = LiveProbeChild(
        ("must-not-be-executed",), env=create_test_environment(), cwd=str(tmp_path)
    )
    runner.cancel()
    result = runner.run()
    assert result.cancelled and runner.identity is None


def test_source_child_imports_current_package_even_when_caller_cwd_has_same_name(
    tmp_path: Path,
) -> None:
    from gametool.gui_live_subprocess import (
        LiveProbeChild,
        build_live_probe_command,
        build_live_probe_environment,
    )

    shadow = tmp_path / "gametool"
    shadow.mkdir()
    (shadow / "__init__.py").write_text(
        "raise RuntimeError('SHADOW_PACKAGE_MUST_NOT_RUN')\n", encoding="utf-8"
    )
    runner = LiveProbeChild(
        (*build_live_probe_command(LiveCliOptions(), frozen=False), "--help"),
        env=build_live_probe_environment(create_test_environment(), frozen=False),
        cwd=str(tmp_path),
    )

    result = runner.run()

    assert result.exit_code == 0, result.stderr
    assert "live" in result.stdout
    assert "SHADOW_PACKAGE_MUST_NOT_RUN" not in result.stdout + result.stderr


def test_cancel_during_child_creation_reclaims_the_new_owned_process(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import gui_live_subprocess as helper

    script = tmp_path / "stub.py"
    script.write_text(_STUB, encoding="utf-8")
    created, release = threading.Event(), threading.Event()
    original = helper.subprocess.Popen
    processes = []

    def delayed(*args, **kwargs):
        process = original(*args, **kwargs)
        processes.append(process)
        created.set()
        assert release.wait(5)
        return process

    monkeypatch.setattr(helper.subprocess, "Popen", delayed)
    runner = helper.LiveProbeChild(
        (sys.executable, "-X", "utf8", str(script), "hold", str(tmp_path), "race"),
        env=create_test_environment(),
        cwd=str(tmp_path),
    )
    results = []
    thread = threading.Thread(target=lambda: results.append(runner.run()), daemon=True)
    thread.start()
    try:
        assert created.wait(5)
        runner.cancel()
        release.set()
        thread.join(8)
        assert not thread.is_alive() and results[0].cancelled
        assert processes[0].poll() is not None
        if os.name == "nt":
            assert not (tmp_path / "race.pid").exists()
    finally:
        release.set()
        runner.cancel()
        thread.join(5)


class _Widget:
    def __init__(self, value=None) -> None:
        self.value = value
        self.state = "normal"

    def get(self):
        return self.value

    def cget(self, _key):
        return self.state

    def configure(self, **kwargs):
        self.state = kwargs.get("state", self.state)

    def delete(self, *_args):
        pass

    def insert(self, *_args):
        pass


class _WindowHost:
    def __init__(self, label: str, pack: Path) -> None:
        self._probe_closed = False
        self._probe_start_id = None
        self._probe_poll_id = None
        self._probe_child = None
        self._probe_button = _Widget()
        self._copy_hint = _Widget()
        self._output = _Widget()
        self._pack_dir_provider = None
        self._pack_dir = str(pack)
        self._var_players = _Widget(True)
        self._var_all_units = _Widget(True)
        self._var_resources = _Widget(False)
        self._map_entry = _Widget("")
        self._unit_entry = _Widget(label)
        self.scheduled = {}
        self.finished = []
        self.finish_threads = []
        self._next_after = 0

    def _save_last_unit_query(self, _value):
        pass

    def _save_last_map_path(self, _value):
        pass

    def after(self, _delay, callback):
        self._next_after += 1
        key = str(self._next_after)
        self.scheduled[key] = callback
        return key

    def after_cancel(self, key):
        self.scheduled.pop(key, None)

    def winfo_exists(self):
        return not self._probe_closed

    def _finish(self, message):
        self.finished.append(message)
        self.finish_threads.append(threading.get_ident())

    def pump(self):
        callbacks = tuple(self.scheduled.values())
        self.scheduled.clear()
        for callback in callbacks:
            callback()


def test_actual_two_window_workers_deliver_only_their_own_child_result_on_main_thread(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import gui_live_probe as gui
    from gametool.gui_live_subprocess import LiveProbeChild

    script = tmp_path / "stub.py"
    script.write_text(_STUB, encoding="utf-8")
    children = []

    def child_factory(command, *, env, cwd):
        assert cwd == os.getcwd()
        label = command[command.index("--unit") + 1]
        child = LiveProbeChild(
            (sys.executable, "-X", "utf8", str(script), "emit", str(tmp_path), label),
            env=create_test_environment(),
            cwd=str(tmp_path),
        )
        children.append(child)
        return child

    def unexpected_live(*_args, **_kwargs):
        raise AssertionError("GUI must not run a live CLI in the parent process")

    monkeypatch.setattr(gui, "LiveProbeChild", child_factory)
    monkeypatch.setattr("gametool.live_cli.run_live_cli", unexpected_live)
    windows = [_WindowHost(label, tmp_path) for label in ("A", "B")]
    stdout, stderr = sys.stdout, sys.stderr
    try:
        for window in windows:
            gui.LiveProbeWindow._start(cast(gui.LiveProbeWindow, cast(object, window)))
        _wait_file(tmp_path / "A.pid")
        _wait_file(tmp_path / "B.pid")
        (tmp_path / "B.release").touch()
        (tmp_path / "A.release").touch()
        deadline = monotonic() + 8
        while not all(window.finished for window in windows):
            assert monotonic() < deadline
            for window in windows:
                window.pump()
            sleep(0.01)
        for label, window in zip(("A", "B"), windows):
            code, body = window.finished[0].split(chr(0), 1)
            assert code == "0"
            assert json.loads(body) == {"session": label, "text": "物品" * 100_003}
            assert window.finish_threads == [threading.get_ident()]
        assert sys.stdout is stdout and sys.stderr is stderr
    finally:
        for window in windows:
            gui.LiveProbeWindow._cancel_live_probe(
                cast(gui.LiveProbeWindow, cast(object, window))
            )
        for child in children:
            child.cancel()
