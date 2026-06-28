"""Persistent per-module load options for the GUI."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

OBJECT_BROWSER_KEY: Final = "object_browser"
MAP_INFO_KEY: Final = "map_info"
PREPLACED_KEY: Final = "preplaced"
COMMANDS_KEY: Final = "commands"
RECIPES_KEY: Final = "recipes"
ORPHANS_KEY: Final = "orphans"
REPORTS_KEY: Final = "reports"


@dataclass(frozen=True, slots=True)
class LoadOptionSpec:
    key: str
    label: str
    description: str


LOAD_OPTION_SPECS: Final = (
    LoadOptionSpec(OBJECT_BROWSER_KEY, "对象档案馆", "对象名字列表与右侧详情图标"),
    LoadOptionSpec(MAP_INFO_KEY, "地图信息", "地图基础信息、玩家、资源和配置"),
    LoadOptionSpec(PREPLACED_KEY, "场景放置", "预放置单位、装饰物与坐标"),
    LoadOptionSpec(COMMANDS_KEY, "触发指令", "脚本聊天指令与隐藏口令扫描"),
    LoadOptionSpec(RECIPES_KEY, "合成配方", "脚本合成逻辑识别"),
    LoadOptionSpec(ORPHANS_KEY, "孤立对象", "引用关系中的未使用对象"),
    LoadOptionSpec(REPORTS_KEY, "总览 / 分析报告", "总览卡片与风险分析报告"),
)


def default_load_options() -> dict[str, bool]:
    return {spec.key: True for spec in LOAD_OPTION_SPECS}


def object_only_load_options() -> dict[str, bool]:
    options = {spec.key: False for spec in LOAD_OPTION_SPECS}
    options[OBJECT_BROWSER_KEY] = True
    return options


def normalize_load_options(raw: Mapping[str, bool] | None) -> dict[str, bool]:
    defaults = default_load_options()
    if raw is None:
        return defaults
    return {key: bool(raw.get(key, default)) for key, default in defaults.items()}


def load_options_from_config(config: Mapping[str, Mapping[str, bool]]) -> dict[str, bool]:
    raw = config.get("load_options")
    return normalize_load_options(raw if isinstance(raw, Mapping) else None)
