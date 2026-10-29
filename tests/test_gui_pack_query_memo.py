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


def test_gui_success_writes_cli_again_memo(tmp_path, monkeypatch) -> None:
    """GUI and CLI share successful-query memory through one execution interface."""
    from typing import cast
    from gametool import pack_query_cli as queries

    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    (tmp_path / "text.tsv").write_text("query target\n", encoding="utf-8")
    window = cast(
        gui_pack_query._PackQueryWindow,
        cast(object, SimpleNamespace(_pack_dir=str(tmp_path))),
    )
    text, _elapsed = gui_pack_query._PackQueryWindow._run_query(window, "text", "query")
    assert "query target" in text
    assert queries._load_last_query() == {
        "pack": str(tmp_path),
        "command": "text",
        "query": "query",
    }
    gui_pack_query._PackQueryWindow._run_query(window, "text", "missing")
    last = queries._load_last_query()
    assert last is not None and last["query"] == "query"


def test_stats_mode_in_panel() -> None:
    """Every command remains selectable with a visible label and a hint."""
    from gametool.gui_pack_query import _PackQueryWindow
    from gametool.gui_pack_query_modes import MODE_ROWS, mode_command, mode_row_labels

    commands = [command for row in MODE_ROWS for command in row]
    visible = [label for row in range(len(MODE_ROWS)) for label in mode_row_labels(row)]
    assert commands[13] == "stats"
    assert commands == [mode_command(label) for label in visible]
    assert len(commands) == len(set(commands)) == 27
    assert set(commands) == set(_PackQueryWindow._PLACEHOLDERS)
    assert "脚本调用" in visible


def test_mode_panel_three_rows() -> None:
    """The actual third-row commands must never highlight the second row."""
    from gametool.gui_pack_query_modes import mode_row_selections

    for command in "price quest cmd text refs affixes registered diff".split():
        assert mode_row_selections(command) == ("<<none>>", "<<none>>", command)
    assert mode_row_selections("calls") == ("<<none>>", "<<none>>", "脚本调用")
    assert mode_row_selections("stats") == ("<<none>>", "stats", "<<none>>")
    assert mode_row_selections("near") == ("near", "<<none>>", "<<none>>")


def test_sel_index_dot_syntax_everywhere() -> None:
    """sel 索引必须用点号形态 ("sel.first") — 空格形态 Tcl 炸 (306 轮真 bug)。"""
    import pathlib as _pl

    for name in ("gui_pack_query.py", "gui_topbar.py", "gui_live_probe.py"):
        src = (_pl.Path(__file__).parents[1] / "gametool" / name).read_text(
            encoding="utf-8"
        )
        assert '"sel first"' not in src, name
        assert '"sel.last"' in src or "sel.first" in src or "sel" not in src, name


def test_coords_clipboard_prefers_selected_block() -> None:
    """剪贴板提取坐标: 探针 JSON 有 selected 块时取其坐标而非全图末尾单位。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow._coords_from_clipboard)
    assert (
        "coordinates_from_text" in src
    )  # 结构化 selected、精确坐标与歧义判断共用解析器


def test_near_rerun_menu_method_exists() -> None:
    """near 迭代右键: 选中坐标行以半径 500 再查 (由远及近逼近)。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    core = inspect.getsource(_PackQueryWindow._near_rerun_from_box)
    assert 'self._switch_mode("near")' in core  # 统一切换入口 (327/328)
    assert "radius" in core  # 半径参数化 (500/100 双档)
    assert "self._run_clicked()" in core  # 直接执行
    whole = inspect.getsource(_PackQueryWindow)
    assert '("100")' in whole  # 精细档菜单已挂


def test_code_rerun_menu_methods() -> None:
    """输出区码 where/drop 直达: 单匹配才发, 走统一切换。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow._code_rerun)
    assert "code_from_text(raw)" in src  # 多匹配拒猜测与四字节身份共用
    assert "self._switch_mode(prefix)" in src  # 统一切换入口
    assert "box if box is not None" in src  # 收藏区同款 (box 参数化)


def test_free_word_list_complete() -> None:
    """免词清单: 空词总览型模式全部在列 (365 轮漏三模式教训——清单也入守卫)。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow
    from gametool.pack_query_options import EMPTY_QUERY_COMMANDS

    src = inspect.getsource(_PackQueryWindow._run)
    assert "EMPTY_QUERY_COMMANDS" in src
    for mode in (
        "stats",
        "list",
        "buffs",
        "skills",
        "units",
        "heroes",
        "synth",
        "affixes",
        "registered",
        "again",
    ):
        assert mode in EMPTY_QUERY_COMMANDS, mode


def test_history_full_retention() -> None:
    """History persists and remains selectable without a display-only ceiling."""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    whole = inspect.getsource(_PackQueryWindow)
    assert "del _HISTORY[10:]" not in whole  # 落盘前截断禁再入仓
    assert "_HISTORY[:12]" not in whole
    assert 'values=[f"{c} {k}".strip() for c, k in _HISTORY]' in whole


def test_diff_mode_wiring() -> None:
    """diff GUI 模式 (373): 记忆旧包 + pack_dir_b 传递 + 空旧包拒发。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    whole = inspect.getsource(_PackQueryWindow)
    # 记忆读写方法在位 (fail-open 同款口径)
    assert "_diff_against" in whole
    assert "diff-against.txt" in whole
    # _run_query 传 pack_dir_b (CLI 同款语义: 关键词=旧包路径优先, 记忆兑底)
    qsrc = inspect.getsource(_PackQueryWindow._run_query)
    assert "pack_dir_b=pack_b" in qsrc
    assert "_diff_against()" in qsrc
    # 空旧包且无记忆时拒发 (不再落在 CLI 的笼统「需要四码或名称」)
    rsrc = inspect.getsource(_PackQueryWindow._run)
    assert "diff 需要旧包目录" in rsrc
