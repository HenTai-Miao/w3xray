"""PID-bound visual reads cannot borrow memory access or imply memory evidence."""

from __future__ import annotations

import ctypes
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from gametool import live_cli
from tests.test_real_session_live_capture import capture_apis as capture_apis


@pytest.fixture
def icons_probe(capture_apis, monkeypatch):
    live, user, gdi = capture_apis
    monkeypatch.setattr(live, "find_war3_pids", Mock(return_value=[42]))
    monkeypatch.setattr(live, "mem_setup", Mock())
    monkeypatch.setattr(live, "open_process", Mock(return_value=0))
    monkeypatch.setattr(
        live, "snapshot", Mock(side_effect=AssertionError("no real scan"))
    )
    monkeypatch.setattr(
        live, "detect_version", Mock(side_effect=AssertionError("no version read"))
    )
    monkeypatch.setattr(
        live, "build_templates", Mock(return_value=({"I001": "fixture"}, {}))
    )
    monkeypatch.setattr(
        live,
        "match_inventory",
        Mock(return_value=[(0.99, "I001", "fixture item", (10, 20), 32)]),
    )
    monkeypatch.setattr(live, "append_live_journal", lambda _report: None)
    return live, user, gdi


def test_explicit_icons_succeeds_without_openprocess_or_memory_features(icons_probe):
    live, user, _gdi = icons_probe

    report = live.read_live("unused", strategy="icons", pid=42, verbose=False)

    assert report["strategy_used"] == "icons"
    assert report["pid"] == 42
    assert report["slots"][0]["item"] == "I001"
    assert report["version"] is None
    assert report["selected_unit"] is None
    assert report["owned_units"] is None and report["all_units"] is None
    assert report["resources"] is None and report["player_rows"] is None
    assert any("像素" in note and "归属" in note for note in report["notes"])
    live.open_process.assert_not_called()
    live.mem_setup.assert_not_called()
    live.snapshot.assert_not_called()
    live.detect_version.assert_not_called()
    user.PrintWindow.assert_called_once_with(101, 301, 3)


def test_capture_uses_the_explicit_pid_among_same_title_windows(capture_apis):
    live, user, _gdi = capture_apis
    user.windows = {
        101: {"pid": 111, "title": "Warcraft III"},
        202: {"pid": 222, "title": "Warcraft III"},
    }

    image, size = live.capture_window(pid=222)

    assert image.size == size == (2, 1)
    user.PrintWindow.assert_called_once_with(202, 301, 3)


def test_caption_length_overestimate_does_not_erase_a_confirmed_window(capture_apis):
    live, user, _gdi = capture_apis
    user.GetWindowTextLengthW.side_effect = lambda _hwnd: len("Warcraft III") + 4

    image, size = live.capture_window(pid=42)

    assert image.size == size == (2, 1)
    user.PrintWindow.assert_called_once_with(101, 301, 3)


def test_explicit_missing_pid_never_falls_back_to_another_game(icons_probe):
    live, user, _gdi = icons_probe

    report = live.read_live("unused", strategy="icons", pid=99, verbose=False)

    assert report["slots"] == []
    assert any("--pid 99" in note for note in report["notes"])
    live.open_process.assert_not_called()
    user.PrintWindow.assert_not_called()


@pytest.mark.parametrize("pid", (None, 222))
def test_ambiguous_windows_never_pick_the_first_title(capture_apis, pid):
    live, user, _gdi = capture_apis
    user.windows = {
        101: {"pid": 222, "title": "Warcraft III"},
        202: {"pid": 222, "title": "Warcraft III"},
    }

    with pytest.raises(RuntimeError, match="多个.*窗口"):
        live.capture_window(pid=pid)
    user.PrintWindow.assert_not_called()


def test_unbound_matching_window_blocks_a_guessed_unique_target(capture_apis):
    live, user, _gdi = capture_apis
    user.windows = {
        101: {"pid": 0, "title": "Warcraft III"},
        202: {"pid": 222, "title": "Warcraft III"},
    }

    with pytest.raises(RuntimeError, match="PID"):
        live.capture_window(pid=222)
    user.PrintWindow.assert_not_called()


def test_capture_discards_a_frame_after_window_pid_changes(capture_apis):
    live, user, gdi = capture_apis

    def changed_window(*_args):
        user.windows[101]["pid"] = 99
        return 1

    user.PrintWindow.side_effect = changed_window
    with pytest.raises(RuntimeError, match="(PID|身份)"):
        live.capture_window(pid=42)
    gdi.DeleteObject.assert_called_once_with(401)
    gdi.DeleteDC.assert_called_once_with(301)
    user.ReleaseDC.assert_called_once_with(101, 201)


def test_auto_fallback_keeps_requested_pid_and_process_identity_guard(
    icons_probe, monkeypatch
):
    from gametool import hero_chain

    live, user, _gdi = icons_probe
    user.windows = {
        101: {"pid": 111, "title": "Warcraft III"},
        202: {"pid": 222, "title": "Warcraft III"},
    }
    live.find_war3_pids.return_value = [111, 222]
    live.open_process.return_value = 123
    live.snapshot.side_effect = None
    live.snapshot.return_value = ([], 0)
    live.detect_version.side_effect = None
    live.detect_version.return_value = {
        "engine": "classic",
        "arch": "x86",
        "version": "fixture",
        "game_dll": None,
    }
    monkeypatch.setattr(live, "_process_identity", lambda _handle: "war3.exe")
    monkeypatch.setattr(live, "_integrity_rid", lambda _handle: None)
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=Mock()))
    monkeypatch.setattr(live, "verify_opened_process", Mock(return_value=None))
    monkeypatch.setattr(hero_chain, "read_inventory", lambda *_args, **_kwargs: [])

    report = live.read_live("unused", strategy="auto", pid=222, verbose=False)

    assert report["strategy_used"] == "icons" and report["pid"] == 222
    user.PrintWindow.assert_called_once_with(202, 301, 3)
    live.open_process.assert_called_once_with(222)
    live.verify_opened_process.assert_called_once_with(123, "war3.exe")
    live.k32.CloseHandle.assert_called_once_with(123)


def test_multiple_processes_still_require_explicit_pid_for_icons(icons_probe):
    live, user, _gdi = icons_probe
    live.find_war3_pids.return_value = [111, 222]

    report = live.read_live("unused", strategy="icons", verbose=False)

    assert report["slots"] == []
    assert any("--pid" in note for note in report["notes"])
    user.PrintWindow.assert_not_called()


def test_black_visual_frame_remains_indeterminate_and_fails_cli(
    icons_probe, monkeypatch, capsys
):
    live, _user, gdi = icons_probe

    def black(_dc, _bitmap, _start, lines, buffer, _info, _usage):
        ctypes.memmove(buffer, bytes((0, 0, 0, 255)) * 2, 8)
        return lines

    gdi.GetDIBits.side_effect = black
    report = live.read_live("unused", strategy="icons", pid=42, verbose=False)
    assert report["slots"] == [] and report["strategy_used"] is None
    assert any("纯色空帧" in note for note in report["notes"])
    live.match_inventory.assert_not_called()
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: report)
    assert live.main(["--pack", "unused", "--strategy", "icons", "--pid", "42"]) == 2
    assert "不能" in capsys.readouterr().out


_MEMORY_REQUESTS = (
    ({"players": True}, "--players"),
    ({"all_units": True}, "--all-units"),
    ({"resources": "auto"}, "--resources"),
    ({"unit_query": "H004"}, "--unit"),
    ({"nick": "1=fixture"}, "--nick"),
    ({"profile_json": "fixture.json"}, "--profile-json"),
    ({"export_profile": "fixture.json"}, "--export-profile"),
    ({"save_snapshot_dir": "fixture"}, "--save-snapshot"),
    ({"load_snapshot_dir": "fixture"}, "--load-snapshot"),
)


@pytest.mark.parametrize(("memory_options", "option"), _MEMORY_REQUESTS)
def test_icons_rejects_memory_options_as_structured_input_error(
    icons_probe, monkeypatch, memory_options, option, capsys
):
    live, user, _gdi = icons_probe

    report = live.read_live(
        "unused", strategy="icons", pid=42, verbose=False, **memory_options
    )

    assert report["input_error"] is True
    assert any(option in note and "内存" in note for note in report["notes"])
    live.open_process.assert_not_called()
    user.PrintWindow.assert_not_called()
    monkeypatch.setattr(
        live,
        "read_live",
        lambda *_args, **_kwargs: {**report, "slots": [{"item": "decoy"}]},
    )
    assert live.main(["--pack", "unused"]) == 2
    capsys.readouterr()


@pytest.mark.parametrize(("memory_options", "option"), _MEMORY_REQUESTS)
def test_cli_icons_memory_options_fail_before_pack_preparation(
    monkeypatch, memory_options, option, capsys
):
    values = dict(memory_options)
    for old, new in (
        ("save_snapshot_dir", "save_snapshot"),
        ("load_snapshot_dir", "load_snapshot"),
    ):
        if old in values:
            values[new] = values.pop(old)
    if "resources" in values:
        values["resources"] = ("auto", "")
    monkeypatch.setattr(
        live_cli,
        "_ensure_pack_dir",
        Mock(side_effect=AssertionError("must not prepare a pack")),
    )

    code = live_cli.run_live_cli(
        live_cli.LiveCliOptions(pack_dir="unused", strategy="icons", **values)
    )

    assert code == 2
    error = capsys.readouterr().err
    assert "参数" in error and option in error and "内存" in error


def test_direct_offline_icons_also_rejects_ignored_memory_options(icons_probe, capsys):
    live, user, _gdi = icons_probe

    with pytest.raises(SystemExit) as failure:
        live.main(
            [
                "--pack",
                "unused",
                "--strategy",
                "icons",
                "--test-image",
                "must-not-open.png",
                "--players",
            ]
        )
    assert failure.value.code == 2
    assert "--players" in capsys.readouterr().err
    user.PrintWindow.assert_not_called()
