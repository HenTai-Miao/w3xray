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


def test_stats_mode_in_panel() -> None:
    """stats 总览模式在模式面板第 14 位 (查看型, 关键词可空)。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow)
    assert src.count('"stats",') >= 2  # _mode_commands + SegmentedButton values
    assert src.count('"shop",') >= 2 and src.count('"tech",') >= 2  # 16 模式 (322)
    assert src.count('"item",') >= 2 and src.count('"heroes",') >= 2  # 18 模式 (323)
    assert src.count('"quest",') >= 2 and src.count('"cmd",') >= 2  # 21 模式 (338)
    assert (
        src.count('"text",') >= 3
        and src.count('"refs",') >= 3
        and src.count('"affixes",') >= 3
        and src.count('"registered",')
        >= 3  # 25 模式 (三排重整后三处=二排 values+两名单, 342/344/363)
    )  # 23 模式 (339/340, 列表+名单+placeholder)
    assert '"stats":' in src  # placeholder 表


def test_mode_panel_three_rows() -> None:
    """23 模式三排布局: 主排+扩展排+扩展二排, 双排高亮互斥。"""
    import inspect

    from gametool.gui_pack_query import _PackQueryWindow

    src = inspect.getsource(_PackQueryWindow)
    assert "_mode_extra2" in src  # 扩展二排
    assert (
        src.count('_mode_extra2.set("<<none>>")') >= 3
    )  # 构造占位+切换+初开双排互斥清显


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
    assert '"selected"' in src  # selected 块优先
    assert "xs[-1]" in src  # 兜底仍在 (无 selected 时退最后一对)


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
    assert "len(matches) != 1" in src  # 多匹配拒猜测
    assert "self._switch_mode(prefix)" in src  # 统一切换入口
    assert "box if box is not None" in src  # 收藏区同款 (box 参数化)
