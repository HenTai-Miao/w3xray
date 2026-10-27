"""Real-session regressions for live request wiring; never read a game process."""

from __future__ import annotations

import base64
import ctypes
from dataclasses import replace
import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import live_cli


def test_gui_resources_checkbox_requests_supported_auto_protocol(monkeypatch, tmp_path):
    from gametool import gui_live_probe
    from gametool.gui_live_subprocess import LiveProbeResult

    requested = []
    widget = SimpleNamespace(
        cget=lambda _name: "normal",
        configure=lambda **_kwargs: None,
        delete=lambda *_args: None,
        insert=lambda *_args: None,
    )
    window = SimpleNamespace(
        _probe_closed=False,
        _probe_start_id=None,
        _probe_child=None,
        _probe_poll_id=None,
        _probe_button=widget,
        _copy_hint=widget,
        _output=widget,
        _pack_dir_provider=None,
        _pack_dir=str(tmp_path),
        _var_players=SimpleNamespace(get=lambda: False),
        _var_all_units=SimpleNamespace(get=lambda: True),
        _var_resources=SimpleNamespace(get=lambda: True),
        _map_entry=SimpleNamespace(get=lambda: ""),
        _unit_entry=SimpleNamespace(get=lambda: "H004"),
        _save_last_unit_query=lambda _value: None,
        _save_last_map_path=lambda _value: None,
        after=lambda *_args: None,
    )
    monkeypatch.setattr(
        gui_live_probe.threading,
        "Thread",
        lambda *, target, daemon: SimpleNamespace(start=target),
    )
    monkeypatch.setattr(
        gui_live_probe,
        "build_live_probe_command",
        lambda options: requested.append(options) or ("isolated-probe-stub",),
    )
    monkeypatch.setattr(
        gui_live_probe,
        "LiveProbeChild",
        lambda *_args, **_kwargs: SimpleNamespace(
            run=lambda: LiveProbeResult(0, "{}", ""),
        ),
    )

    gui_live_probe.LiveProbeWindow._start(
        cast(gui_live_probe.LiveProbeWindow, cast(object, window))
    )

    assert len(requested) == 1
    assert requested[0].resources == ("auto", "")
    assert requested[0].all_units is True
    assert requested[0].unit_query == "H004"


@pytest.mark.parametrize(
    "values", (("reported", "reported"), ("nan", "2"), ("1", "inf"))
)
def test_invalid_programmatic_resources_fail_before_pack_or_memory(
    monkeypatch, capsys, values
):
    def forbidden(*_args):
        pytest.fail("An invalid resource request must fail before preparing a pack")

    monkeypatch.setattr(live_cli, "_ensure_pack_dir", forbidden)
    code = live_cli.run_live_cli(
        live_cli.LiveCliOptions(pack_dir="unused", resources=values)
    )

    assert code == 2
    assert "--resources" in capsys.readouterr().err


@pytest.mark.parametrize("values", (("nan", "2"), ("1", "inf")))
def test_resource_cli_rejects_nonfinite_hud_values(values):
    with pytest.raises(live_cli.LiveCliOptionError, match="--resources"):
        live_cli.parse_live_cli_options(("--pack", "unused", "--resources", *values))


@pytest.mark.parametrize("values", (("reported", "reported"), ("nan", "2")))
def test_direct_inventory_cli_rejects_invalid_resources_before_probe(
    monkeypatch, capsys, values
):
    from gametool import live_inventory

    def forbidden(*_args, **_kwargs):
        pytest.fail("An invalid resource request must never reach read_live")

    monkeypatch.setattr(live_inventory, "read_live", forbidden)
    with pytest.raises(SystemExit) as failure:
        live_inventory.main(["--pack", "unused", "--resources", *values])

    assert failure.value.code == 2
    assert "--resources" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("values", "expected"),
    ((("auto", ""), "auto"), (("169.25", "808"), (169.25, 808.0))),
)
def test_valid_resource_modes_reach_the_probe(monkeypatch, tmp_path, values, expected):
    from gametool import live_inventory

    captured = []

    def probe(*_args, **kwargs):
        captured.append(kwargs)
        return {
            "slots": [],
            "strategy_used": None,
            "resources": [],
        }

    monkeypatch.setattr(live_inventory, "read_live", probe)
    monkeypatch.setattr(live_inventory, "append_live_journal", lambda _report: None)

    code = live_cli.run_live_cli(
        live_cli.LiveCliOptions(pack_dir=str(tmp_path), resources=values)
    )

    assert code == 0
    assert captured[0]["resources"] == expected
    assert captured[0]["players"] is True


def test_elevated_dump_hint_never_executes_the_dump(monkeypatch, capsys, tmp_path):
    from gametool import live_object_dump

    def forbidden(*_args):
        pytest.fail("A print-only hint must not inspect a running game")

    monkeypatch.setattr(live_object_dump, "dump_live_objects", forbidden)
    options = live_cli.LiveCliOptions(
        dump_objects=str(tmp_path / "object dump"), pid="8728", elevated_hint=True
    )

    assert live_cli.run_live_cli(options) == 0
    assert "--dump-objects" in capsys.readouterr().out


def _windows_argv(arguments: str) -> list[str]:
    shell32 = ctypes.WinDLL("shell32", use_last_error=True)
    shell32.CommandLineToArgvW.argtypes = [
        ctypes.c_wchar_p,
        ctypes.POINTER(ctypes.c_int),
    ]
    shell32.CommandLineToArgvW.restype = ctypes.POINTER(ctypes.c_wchar_p)
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.LocalFree.argtypes = [ctypes.c_void_p]
    kernel32.LocalFree.restype = ctypes.c_void_p
    count = ctypes.c_int()
    result = shell32.CommandLineToArgvW("fixture.exe " + arguments, ctypes.byref(count))
    if not result:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return [result[index] for index in range(1, count.value)]
    finally:
        kernel32.LocalFree(ctypes.cast(result, ctypes.c_void_p))


def _capture_printed_process(command: str) -> dict[str, str]:
    """Let PowerShell parse its literals while replacing Start-Process completely."""
    powershell = shutil.which("pwsh") or shutil.which("powershell")
    if powershell is None:
        pytest.skip("PowerShell parser is unavailable")
    script = (
        """
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
function Start-Process {
    param([string]$FilePath, [string]$ArgumentList, [string]$WorkingDirectory,
          [string]$Verb, [switch]$Wait, [switch]$NoNewWindow)
    @{FilePath=$FilePath; ArgumentList=$ArgumentList; WorkingDirectory=$WorkingDirectory;
      Verb=$Verb; Encoding=$env:PYTHONIOENCODING} | ConvertTo-Json -Compress
}
"""
        + command
    )
    encoded = base64.b64encode(script.encode("utf-16le")).decode("ascii")
    completed = subprocess.run(
        [powershell, "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=True,
    )
    return json.loads(completed.stdout)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows command-line parsing")
@pytest.mark.parametrize("resources", (("auto", ""), ("169.25", "808")))
@pytest.mark.parametrize("frozen", (False, True))
def test_elevated_hint_roundtrips_full_request_without_starting_it(
    monkeypatch, capsys, tmp_path, resources, frozen
):
    def forbidden(*_args):
        pytest.fail("The printed hint must not prepare a pack or inspect a game")

    monkeypatch.setattr(live_cli, "_ensure_pack_dir", forbidden)
    monkeypatch.setattr(sys, "frozen", frozen, raising=False)
    if frozen:
        monkeypatch.setattr(sys, "executable", str(tmp_path / "GameXRay.exe"))
    # An installed wheel has no main.py beside its package directory.
    monkeypatch.setattr(
        live_cli,
        "__file__",
        str(tmp_path / "site-packages" / "gametool" / "live_cli.py"),
    )
    options = live_cli.LiveCliOptions(
        map_path=str(tmp_path / "O'Brien map.w3x"),
        pack_dir=str(tmp_path / "资料 O'Brien pack"),
        strategy="handle",
        test_image=str(tmp_path / "截屏.png"),
        save_snapshot=str(tmp_path / "save snapshot"),
        load_snapshot=str(tmp_path / "load snapshot"),
        unit_query='名字 "quoted" H004',
        players=True,
        all_units=True,
        resources=resources,
        nick="1=O'Brien,2=队友",
        export_profile=str(tmp_path / "export profile.json"),
        profile_json=str(tmp_path / "input profile.json"),
        pid="8728",
        elevated_hint=True,
    )

    assert live_cli.run_live_cli(options) == 0
    output = capsys.readouterr().out
    command = next(
        line.strip() for line in output.splitlines() if "Start-Process" in line
    )
    elevated = _capture_printed_process(command)
    assert elevated["Verb"] == "RunAs"
    shell_args = _windows_argv(elevated["ArgumentList"])
    script = shell_args[shell_args.index("-Command") + 1]
    python = _capture_printed_process(script)
    assert Path(python["FilePath"]).resolve() == Path(sys.executable).resolve()
    assert python["Encoding"] == "utf-8"
    argv = _windows_argv(python["ArgumentList"])
    prefix = ["live"] if frozen else ["-X", "utf8", "-m", "gametool", "live"]
    assert argv[: len(prefix)] == prefix
    assert live_cli.parse_live_cli_options(argv[len(prefix) :]) == replace(
        options, elevated_hint=False
    )
    assert Path(elevated["WorkingDirectory"]).resolve() == Path.cwd()
