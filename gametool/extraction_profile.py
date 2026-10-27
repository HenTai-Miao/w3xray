"""提取类目开关 (ExtractionProfile) — 按组跳过资料包产物以提速。

设计约束:
- 类目键是**通用概念** (物品/单位/技能/触发逻辑/关系/世界/预放置/脚本/资源/基础信息),
  不绑定任何特定游戏; 游戏专属的「类目→产物文件」映射由 gametool/games/<游戏>/ 提供。
- profile 只决定「要不要产出」, 不改变产出内容的格式——关掉的组完全不写文件,
  开着的组与全量导出逐字节一致 (可复现)。
- 持久化到缓存目录配置 JSON (与 GUI 配置同目录), CLI --profile 与 GUI 设置对话框共用。
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final

from .cache_root import gamexray_cache_root

__all__ = (
    "CATEGORY_BASIC",
    "CATEGORY_OBJECTS",
    "CATEGORY_PREPLACED",
    "CATEGORY_RELATIONS",
    "CATEGORY_RESOURCES",
    "CATEGORY_SCRIPTS",
    "CATEGORY_SKILLS",
    "CATEGORY_TRIGGERS",
    "CATEGORY_UNITS",
    "CATEGORY_WORLD",
    "PROFILE_CONFIG_FILE",
    "ExtractionProfile",
    "all_categories_enabled",
    "load_profile",
    "normalize_profile",
    "parse_profile_arg",
    "profile_config_path",
    "save_profile",
)

# 通用类目键 (游戏无关概念; 游戏层把类目映射到具体产物文件)
CATEGORY_OBJECTS: Final = "objects"  # 物品/技能/单位等对象表与字段
CATEGORY_UNITS: Final = "units"  # 单位表 (独立于对象, 便于只要单位时跳过物品技能)
CATEGORY_SKILLS: Final = "skills"  # 技能/增益表
CATEGORY_TRIGGERS: Final = "triggers"  # 触发器/ECA/聊天指令/脚本机制
CATEGORY_RELATIONS: Final = "relations"  # 掉落与获取/装备技能关系
CATEGORY_WORLD: Final = "world"  # 区域/镜头/声音/地形
CATEGORY_PREPLACED: Final = "preplaced"  # 预放置装饰物；单位由 units 控制
CATEGORY_SCRIPTS: Final = "scripts"  # 脚本可读文本/脚本索引
CATEGORY_RESOURCES: Final = "resources"  # 图标/模型等资源导出
CATEGORY_BASIC: Final = "basic"  # 地图信息/清单/审计等基础报告

ALL_CATEGORIES: Final = (
    CATEGORY_OBJECTS,
    CATEGORY_UNITS,
    CATEGORY_SKILLS,
    CATEGORY_TRIGGERS,
    CATEGORY_RELATIONS,
    CATEGORY_WORLD,
    CATEGORY_PREPLACED,
    CATEGORY_SCRIPTS,
    CATEGORY_RESOURCES,
    CATEGORY_BASIC,
)

# 类目中文标签 (通用概念, 游戏层可附加自己的说明)
CATEGORY_LABELS: Final = {
    CATEGORY_OBJECTS: "对象表（物品等对象ID与字段）",
    CATEGORY_UNITS: "单位表",
    CATEGORY_SKILLS: "技能与增益表",
    CATEGORY_TRIGGERS: "触发器与指令（ECA/聊天指令/机制线索）",
    CATEGORY_RELATIONS: "掉落与获取/装备关系",
    CATEGORY_WORLD: "世界数据（区域/镜头/声音/地形）",
    CATEGORY_PREPLACED: "预放置（装饰物坐标）",
    CATEGORY_SCRIPTS: "脚本文本（可读脚本与索引）",
    CATEGORY_RESOURCES: "资源导出（图标等）",
    CATEGORY_BASIC: "基础报告（地图信息/清单/审计）",
}

PROFILE_CONFIG_FILE: Final = "extraction-profile.json"


@dataclass(frozen=True, slots=True)
class ExtractionProfile:
    """按类目的提取开关; 全 True = 与历史全量导出行为一致。"""

    enabled: dict[str, bool] = field(
        default_factory=lambda: dict.fromkeys(ALL_CATEGORIES, True)
    )

    def allows(self, category: str) -> bool:
        return self.enabled.get(category, True)

    def disabled_categories(self) -> tuple[str, ...]:
        return tuple(c for c in ALL_CATEGORIES if not self.allows(c))

    def summary(self) -> str:
        off = self.disabled_categories()
        if not off:
            return "全类目开启"
        labels = "、".join(CATEGORY_LABELS.get(c, c) for c in off)
        return f"关闭: {labels}"


def all_categories_enabled() -> dict[str, bool]:
    return dict.fromkeys(ALL_CATEGORIES, True)


def normalize_profile(
    raw: Mapping[str, bool] | ExtractionProfile | None,
) -> ExtractionProfile:
    """未知键忽略; 缺省键补 True——与历史行为保持兼容。"""
    if isinstance(raw, ExtractionProfile):
        return raw
    enabled = all_categories_enabled()
    if raw is not None:
        for key in ALL_CATEGORIES:
            if key in raw:
                enabled[key] = bool(raw[key])
    return ExtractionProfile(enabled)


def parse_profile_arg(text: str) -> ExtractionProfile:
    """解析 --profile 参数。

    形态: 逗号分隔类目键; 前缀 `-` 表示关闭, 其余为关闭制 (未列出的全开)。
    `all` = 全开; `objects,units,-triggers` = 关 triggers 其余全开。
    """
    text = text.strip()
    if not text or text.lower() == "all":
        return ExtractionProfile()
    enabled = all_categories_enabled()
    for raw_token in text.split(","):
        token = raw_token.strip()
        if not token:
            continue
        off = token.startswith("-")
        key = token.removeprefix("-").strip()
        if key not in ALL_CATEGORIES:
            valid = ",".join(ALL_CATEGORIES)
            raise ValueError(f"未知提取类目: {key} (可选: {valid})")
        enabled[key] = not off
    return ExtractionProfile(enabled)


def profile_config_path() -> str:
    return str(gamexray_cache_root() / PROFILE_CONFIG_FILE)


def save_profile(profile: ExtractionProfile) -> None:
    """持久化提取开关; 写失败静默 (fail-open, 与缓存纪律一致)。"""
    try:
        os.makedirs(os.path.dirname(profile_config_path()), exist_ok=True)
        with open(profile_config_path(), "w", encoding="utf-8") as handle:
            json.dump(profile.enabled, handle, ensure_ascii=False, indent=1)
    except OSError:
        pass


def load_profile() -> ExtractionProfile:
    """读取持久化开关; 无文件/损坏时回退全开 (fail-open)。"""
    try:
        with open(profile_config_path(), encoding="utf-8") as handle:
            raw = json.load(handle)
    except OSError, ValueError:
        return ExtractionProfile()
    if not isinstance(raw, dict):
        return ExtractionProfile()
    return normalize_profile(
        {k: bool(v) for k, v in raw.items() if k in ALL_CATEGORIES}
    )


def describe_categories() -> Sequence[tuple[str, str]]:
    """类目键与中文标签 (GUI 设置对话框直接消费)。"""
    return tuple((key, CATEGORY_LABELS[key]) for key in ALL_CATEGORIES)
