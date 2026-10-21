"""GUI 最近资料包目录记忆 — save/load 与 fail-open 行为。"""

from __future__ import annotations

import os

import gametool.gui_export_actions as actions


def test_last_pack_memo_roundtrip(tmp_path, monkeypatch) -> None:
    memo = tmp_path / "gui-last-pack.txt"
    monkeypatch.setattr(actions, "_last_pack_memo_path", lambda: str(memo))

    assert actions.load_last_pack_dir() == ""

    actions.save_last_pack_dir("C:/packs/地图/资料包")
    assert memo.read_text(encoding="utf-8") == "C:/packs/地图/资料包"
    assert actions.load_last_pack_dir() == "C:/packs/地图/资料包"


def test_last_pack_memo_fail_open(monkeypatch, tmp_path) -> None:
    # Given: memo path directory cannot be created.
    blocked = tmp_path / "blocked"
    blocked.write_text("", encoding="utf-8")
    monkeypatch.setattr(
        actions, "_last_pack_memo_path", lambda: str(blocked / "sub" / "m.txt")
    )
    # When: saving into an impossible location, then no exception escapes.
    actions.save_last_pack_dir("X")
    # And: reading a missing file yields empty.
    assert actions.load_last_pack_dir() == ""
    assert not os.path.exists(str(blocked / "sub"))
