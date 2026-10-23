"""GUI 最近资料包目录记忆 — save/load 与 fail-open 行为。"""

from __future__ import annotations

from types import SimpleNamespace

import os

import gametool.gui_export_actions as actions

from gametool import gui_pack_query


def test_bind_geometry_memory_ignores_child_destroy(monkeypatch) -> None:
    # <Destroy> 因子控件冒泡触发时不得把子控件 geometry 记成窗口尺寸。
    calls: list[tuple[str, str]] = []
    monkeypatch.setattr(
        gui_pack_query,
        "_remember_geometry",
        lambda win, name: calls.append((name, win.geometry())),
    )
    saved: list[dict[str, str]] = []
    monkeypatch.setattr(
        gui_pack_query,
        "_save_memo",
        lambda: saved.append(dict(gui_pack_query._WINDOW_GEOMETRY)),
    )
    handlers: dict[str, object] = {}
    win = SimpleNamespace(
        geometry=lambda _a=None: "520x360",
        bind=lambda seq, fn: handlers.__setitem__(seq, fn),
    )
    child = SimpleNamespace()
    gui_pack_query.bind_geometry_memory(win, "gui-test", "520x360")
    handler = handlers["<Destroy>"]
    handler(SimpleNamespace(widget=child))  # pyright: ignore[reportCallIssue]
    assert calls == []  # 子控件销毁不记
    handler(
        SimpleNamespace(widget=win)
    )  # 顶层自身销毁才记  # pyright: ignore[reportCallIssue]
    assert calls == [("gui-test", "520x360")]
    assert len(saved) == 1


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


def test_json_toggle_outputs_json_line() -> None:
    """JSON 勾选经 _run 主线程读值传 _run_query 参数 (不经跨线程 tk var 读)。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow._run)
    assert "as_json = self._var_json.get()" in src  # 主线程读
    sig = inspect.signature(_PackQueryWindow._run_query)
    assert "as_json" in sig.parameters


def test_gui_success_writes_cli_again_memo() -> None:
    """GUI 查询成功后 _worker 落 CLI again memo (源码断言: 调用 _store_last_query 且未找到不写)。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow)
    assert "_store_last_query" in src
    assert 'not result.startswith("未找到")' in src
