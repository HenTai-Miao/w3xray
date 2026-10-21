"""Warcraft III 适配器 — 资料包产物文件的类目归属 (唯一权威映射)。

只做「产物文件 → 通用类目」的映射; 核心导出器按此过滤。
新增产物文件时在此登记归属, 导出过滤自动生效。
"""

from __future__ import annotations

from ..extraction_profile import (
    CATEGORY_BASIC,
    CATEGORY_OBJECTS,
    CATEGORY_PREPLACED,
    CATEGORY_RELATIONS,
    CATEGORY_RESOURCES,
    CATEGORY_SCRIPTS,
    CATEGORY_SKILLS,
    CATEGORY_TRIGGERS,
    CATEGORY_UNITS,
    CATEGORY_WORLD,
)
from . import ExportGroup, GameAdapter, register_adapter

__all__ = ("WARCRAFT_ADAPTER",)

WARCRAFT_GROUPS = (
    ExportGroup(
        CATEGORY_BASIC,
        (
            "资料包目录.tsv",
            "需求覆盖.tsv",
            "地图信息.txt",
            "资料包审计.txt",
            "内部文件清单.txt",
            "提取完整性.txt",
            "组件诊断.tsv",
            "资料包写入结果.tsv",
            "配置格式索引.txt",
            "地图与对象ID索引.tsv",
            "对象ID使用摘要.tsv",
            "存档读写线索.tsv",
            "未知文件/",
            "脚本清单.txt",
        ),
        "基础报告与清单",
    ),
    ExportGroup(
        CATEGORY_OBJECTS,
        (
            "对象ID/",
            "盒子兼容ID/",
            "对象字段.tsv",
            "对象文本与图标.tsv",
            "对象完整描述.tsv",
            "UI文本_TRIGSTR.tsv",
            "UI文本引用.tsv",
        ),
        "对象表 (含物品等所有对象ID与字段)",
    ),
    ExportGroup(CATEGORY_UNITS, ("预放置单位.tsv",), "单位表"),
    ExportGroup(
        CATEGORY_SKILLS,
        ("装备技能关系.tsv",),  # 技能侧关系; 掉落获取归 relations
        "技能与增益",
    ),
    ExportGroup(
        CATEGORY_TRIGGERS,
        (
            "触发器树.tsv",
            "触发器ECA.tsv",
            "触发变量.tsv",
            "脚本机制线索.txt",
        ),
        "触发器与指令",
    ),
    ExportGroup(
        CATEGORY_RELATIONS,
        (
            "掉落与获取关系.tsv",
            "关系完整性.txt",
        ),
        "掉落与获取关系",
    ),
    ExportGroup(
        CATEGORY_WORLD,
        (
            "世界区域.tsv",
            "世界镜头.tsv",
            "世界声音.tsv",
            "地形/",
        ),
        "世界数据",
    ),
    ExportGroup(CATEGORY_PREPLACED, ("预放置装饰物.tsv",), "预放置"),
    ExportGroup(CATEGORY_SCRIPTS, ("脚本可读文本/",), "脚本文本"),
    ExportGroup(CATEGORY_RESOURCES, ("资源/",), "资源导出"),
)

WARCRAFT_ADAPTER = register_adapter(
    GameAdapter(
        game_id="warcraft",
        display_name="Warcraft III",
        export_groups=WARCRAFT_GROUPS,
        notes=(
            "MPQ 地图 (.w3x/.w3n) 体系; 对象四码分类按首字母约定",
            "未列出的产物文件默认归 basic 类目 (永远跟随基础开关)",
        ),
    )
)
