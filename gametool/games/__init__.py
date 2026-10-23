"""游戏适配层注册表 — 把「某个游戏」的专属规则从核心管线隔离。

核心原则 (高可用):
- 核心管线 (加载/导出/查询) 只认通用类目 (extraction_profile.ALL_CATEGORIES)
  与通用数据结构; 任何游戏专属规则 (四码分类/导出文件分组/内存结构)
  一律放进本包的子模块。
- 新增游戏支持 = 在本目录新增一个模块并 @register, **不修改核心代码**。
- 未注册游戏回退 WarcraftAdapter 的通用行为 (MPQ 地图体系共享 WoWWar3 格式)。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Final

from ..extraction_profile import ALL_CATEGORIES

__all__ = (
    "ALL_CATEGORIES",
    "ExportGroup",
    "GameAdapter",
    "get_adapter",
    "list_adapters",
    "register_adapter",
)


@dataclass(frozen=True, slots=True)
class ExportGroup:
    """一个导出组: 属于某个通用类目的一批产物文件。

    成员是资料包根目录下的相对路径 (目录以 / 结尾表示整目录)。
    """

    category: str
    files: tuple[str, ...] = ()
    label: str = ""


@dataclass(frozen=True, slots=True)
class GameAdapter:
    """单个游戏的适配器: 身份 + 导出分组映射。"""

    game_id: str
    display_name: str
    export_groups: tuple[ExportGroup, ...] = ()
    notes: tuple[str, ...] = field(default_factory=tuple)


_adapters: dict[str, GameAdapter] = {}


def register_adapter(adapter: GameAdapter) -> GameAdapter:
    """注册游戏适配器 (模块导入时调用; 同 id 后注册覆盖先注册)。"""
    _adapters[adapter.game_id] = adapter
    return adapter


def get_adapter(game_id: str | None = None) -> GameAdapter:
    """按 id 取适配器; 未指定/未注册时回退魔兽通用适配器。"""
    if game_id and game_id in _adapters:
        return _adapters[game_id]
    return _adapters.get("warcraft", _FALLBACK)


def list_adapters() -> tuple[GameAdapter, ...]:
    return tuple(_adapters.values())


_FALLBACK: Final = GameAdapter(game_id="generic", display_name="通用 (未注册游戏)")
