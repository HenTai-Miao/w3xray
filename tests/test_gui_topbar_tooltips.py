"""顶栏按钮 hover tooltip — 七按钮接入与 _attach_tooltip 助手存在性锁定。"""

from __future__ import annotations

import re
from pathlib import Path

_TOPBAR = Path(__file__).resolve().parents[1] / "gametool" / "gui_topbar.py"
_BUTTONS = (
    "open_map_button",
    "current_map_button",
    "profile_settings_button",
    "pack_query_button",
    "live_probe_button",
    "minimap_button",
    "guide_button",
    "data_tools_button",
    "map_label",
)


def _calls() -> list[str]:
    """返回源码中所有 _attach_tooltip(app.xxx 按钮调用的按钮名 (跨行归一)。"""
    src = _TOPBAR.read_text(encoding="utf-8")
    normalized = re.sub(r"\s+", " ", src)
    return re.findall(r"_attach_tooltip\(\s*app\.(\w+)", normalized)


def test_attach_tooltip_helper_exists() -> None:
    src = _TOPBAR.read_text(encoding="utf-8")
    assert "def _attach_tooltip(widget, text: str) -> None:" in src
    assert '"<Enter>"' in src and '"<Leave>"' in src and '"<ButtonPress>"' in src


def test_seven_buttons_have_tooltips() -> None:
    calls = set(_calls())
    for btn in _BUTTONS:
        assert btn in calls, f"缺少 tooltip: {btn}"


def test_no_duplicate_tooltips() -> None:
    calls = _calls()
    assert len(calls) == len(set(calls)), f"重复 tooltip: {calls}"
    assert len(calls) == 9  # 包查询 + live 探针 + 完整地图名


def test_guide_near_reverse_guard() -> None:
    """guide near 反查: 模板行 near x y 直采纳; 全选 >4 数字拒绝猜测。"""
    src = (Path(__file__).parents[1] / "gametool" / "gui_topbar.py").read_text(
        encoding="utf-8"
    )
    assert "coordinates_from_text" in src  # 精确模板与多坐标拒猜测共用同一解析器
    assert 'radius: str = ""' in src  # 半径参数化 (guide 双档 320)
    assert 'box, "100")' in src  # 精细档菜单


def test_guide_code_menu_multi_match_guard() -> None:
    """guide 码直达: 单匹配才发 (拒猜测), prefix 路由 where/drop/doc。"""
    src = (Path(__file__).parents[1] / "gametool" / "gui_topbar.py").read_text(
        encoding="utf-8"
    )
    assert "code_from_text(raw)" in src  # 多面板共用完整四码与多匹配拒猜测边界
    assert "if code is None:" in src
    assert '_code_selected(app, box, "drop")' in src  # 三键菜单
