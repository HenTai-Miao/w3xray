"""Public offline handoffs retain map identity and use their real CLI parsers."""

from __future__ import annotations

import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

from gametool import app, gui_topbar


@pytest.mark.parametrize("loaded", (False, True))
def test_save_workspace_captures_optional_map_without_requiring_it(
    monkeypatch: pytest.MonkeyPatch, loaded: bool
) -> None:
    from gametool import gui_save_workspace

    original = object() if loaded else None
    host = SimpleNamespace(map_data=original)
    calls = []
    monkeypatch.setattr(
        gui_save_workspace,
        "open_save_workspace",
        lambda parent, **kwargs: calls.append((parent, kwargs)),
    )
    gui_topbar._open_save_workspace(host)
    host.map_data = object()
    assert calls == [(host, {"map_data": original})]


def test_offline_hotkey_entry_requires_no_map_or_process(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import gui_hotkey_config

    host = SimpleNamespace()
    calls = []
    monkeypatch.setattr(gui_hotkey_config, "open_hotkey_config_dialog", calls.append)
    gui_topbar._open_hotkey_config(host)
    assert calls == [host]


def test_main_dispatches_real_hotkeys_help_without_creating_gui(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    from gametool import gui

    def unexpected_gui() -> None:
        pytest.fail("A public offline help command must never open the GUI")

    monkeypatch.setattr(gui, "App", unexpected_gui)
    monkeypatch.setattr(sys, "argv", ["gamexray", "hotkeys", "--help"])
    with pytest.raises(SystemExit) as stopped:
        app.main()
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    assert "inspect" in help_text and "diff" in help_text
    assert "hotkeys" in app.top_level_help()


def test_main_reference_accepts_a_real_external_id_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    table = tmp_path / "物品ID.txt"
    table.write_bytes(
        "ID：I.01\r\n名字：本地来源验收物品\r\n描述：第一行\r\n\r\n第二行\r\n".encode(
            "gb18030"
        )
    )
    original = table.read_bytes()
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "gamexray",
            "reference",
            "本地来源验收物品",
            "--id-table",
            str(table),
            "--kind",
            "objects",
            "--json",
        ],
    )
    with pytest.raises(SystemExit) as stopped:
        app.main()
    assert stopped.value.code == 0
    payload = json.loads(capsys.readouterr().out)
    records = payload["records"]
    assert len(records) == 1
    assert records[0]["id"] == "I.01"
    assert records[0]["scope"] == "external"
    assert records[0]["state"] == "external-unverified"
    assert "第二行" in json.dumps(records[0], ensure_ascii=False)
    assert table.read_bytes() == original
