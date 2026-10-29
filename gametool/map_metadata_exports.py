"""Complete readable map metadata and byte-attributed JSON evidence exports."""

from __future__ import annotations

from dataclasses import asdict, fields
import json

from .extraction_diagnostics import DiagnosticSeverity
from .map_data import MapData
from .w3f import w3f_info_to_dict
from .w3i import W3iInfo, w3i_info_to_dict
from .wts_models import wts_report_to_dict


_HEADER_LABELS = {
    "camera_bounds": "镜头边界（8 个分量）",
    "camera_margins": "镜头补足（4 个分量）",
    "map_version": "地图保存版本",
    "editor_version": "编辑器版本",
    "game_version": "游戏版本（4 个分量）",
    "flags": "原始地图标志",
    "tileset": "主地表",
    "loading_screen_background": "载入背景编号",
    "race_hud": "地图种族界面标志",
    "loading_screen_path": "载入画面路径",
    "loading_screen_text": "载入画面正文",
    "loading_screen_title": "载入画面标题",
    "loading_screen_subtitle": "载入画面副标题",
    "game_data_set": "游戏数据集",
    "prologue_screen_background": "序章背景编号",
    "prologue_screen_path": "序章画面路径",
    "prologue_screen_text": "序章正文",
    "prologue_screen_title": "序章标题",
    "prologue_screen_subtitle": "序章副标题",
    "fog_style": "雾类型",
    "fog_start": "雾起始高度",
    "fog_end": "雾结束高度",
    "fog_density": "雾密度",
    "fog_color_bgra": "雾颜色（BGRA）",
    "fog_height_start": "高度雾起点",
    "fog_height_end": "高度雾终点",
    "fog_linear_start": "线性雾起点",
    "fog_linear_end": "线性雾终点",
    "fog_max_opacity": "雾最大不透明度",
    "fog_draw_over_sky": "天空雾原值",
    "weather_id": "天气 ID",
    "sound_environment": "声音环境",
    "light_environment": "光照地表",
    "water_color_bgra": "水面颜色（BGRA）",
    "script_language_raw": "脚本语言原值",
    "supported_modes": "支持画质标志",
    "game_data_version": "游戏数据版本",
    "default_camera_zoom": "默认镜头缩放原值",
    "max_camera_zoom": "最大镜头缩放原值",
    "min_camera_zoom": "最小镜头缩放原值",
    "hd_water_min_opacity": "HD 水面最小不透明度原值",
    "hd_water_max_opacity": "HD 水面最大不透明度原值",
    "hd_water_reflectivity": "HD 水面反射率原值",
    "hd_water_emissivity": "HD 水面自发光原值",
    "hd_water_edge_softness": "HD 水面边缘柔和度原值",
    "hd_water_wave_displacement": "HD 水面波浪位移原值",
    "hd_water_wave_normal_strength": "HD 水面波浪法线强度原值",
    "hd_water_color_bgra": "HD 水面颜色（BGRA）",
    "hd_water_envmap_reflectivity": "HD 水面环境贴图反射率原值",
    "alpha_tile_minimap_color_bgra": "透明地块小地图颜色（BGRA）",
    "legacy_tail_reserved": "旧格式尾部保留值",
}
_HEADER_HANDLED = frozenset(
    (
        "version",
        "map_name",
        "author",
        "description",
        "recommended_players",
        "width",
        "height",
        "script_type",
        "disable_preview",
        "custom_ally",
        "melee",
        "large_map",
        "custom_forces",
        "custom_techtree",
        "custom_ability",
        "custom_upgrade",
        "players",
        "forces",
        "parse_issue",
        "upgrades",
        "techs",
        "random_unit_tables",
        "random_item_tables",
        "optional_data_skipped",
        "fields",
        "diagnostics",
        "header_complete",
        "tables_complete",
        "complete",
        "consumed_bytes",
        "unconsumed_data",
    )
)
_FLAG_LABELS = (
    ("disable_preview", "禁用预览"),
    ("custom_ally", "自定义同盟优先级"),
    ("melee", "对战地图"),
    ("large_map", "大型地图标记"),
    ("custom_forces", "自定义队伍"),
    ("custom_techtree", "自定义科技树"),
    ("custom_ability", "自定义技能"),
    ("custom_upgrade", "自定义升级"),
)


def format_map_metadata_evidence(md: MapData) -> str:
    """Retain complete map/campaign metadata and their separate boundaries."""
    return _json(
        {
            "schema": "gamexray.map-metadata.v1",
            "map_path": md.path,
            "map_name": md.name,
            "source": "war3map.w3i",
            "source_listed": _listed(md, "war3map.w3i"),
            "complete": md.w3i.complete if md.w3i is not None else False,
            "w3i": w3i_info_to_dict(md.w3i) if md.w3i is not None else None,
            "diagnostics": _component_diagnostics(md, "w3i"),
            "campaign_source": "war3campaign.w3f",
            "campaign_source_listed": _listed(md, "war3campaign.w3f"),
            "campaign_complete": md.w3f.complete if md.w3f is not None else False,
            "w3f": w3f_info_to_dict(md.w3f) if md.w3f is not None else None,
            "campaign_diagnostics": _component_diagnostics(md, "w3f"),
        }
    )


def format_map_string_evidence(md: MapData) -> str:
    """Keep every map/campaign WTS domain separate, including conflicting rows."""
    diagnostics = _component_diagnostics(md, "wts")
    return _json(
        {
            "schema": "gamexray.map-strings.v1",
            "map_path": md.path,
            "map_name": md.name,
            "parsed_source_count": len(md.wts_reports),
            "complete": bool(md.wts_reports)
            and all(report.complete for report in md.wts_reports.values())
            and not any(
                item.component == "wts" and item.severity != DiagnosticSeverity.INFO
                for item in md.diagnostics
            ),
            "sources": [
                {"member": member, **wts_report_to_dict(report)}
                for member, report in md.wts_reports.items()
            ],
            "diagnostics": diagnostics,
        }
    )


def _json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n"


def _listed(md: MapData, name: str) -> bool:
    return any(path.replace("\\", "/").casefold() == name for path in md.all_files)


def _component_diagnostics(md: MapData, component: str) -> list[dict[str, object]]:
    return [asdict(item) for item in md.diagnostics if item.component == component]


def format_w3i_metadata(info: W3iInfo) -> list[str]:
    """Render every semantic header field and table instance without row limits."""
    lines = _format_header(info)
    lines.extend(_format_players(info))
    lines.extend(_format_forces(info))
    lines.extend(_format_tables(info))
    if info.fields or info.diagnostics:
        lines.append(
            f"\nW3I 解析：{'完整' if info.complete else '部分或存在未知值'}"
            f"；头部{'完整' if info.header_complete else '未完整'}"
            f"；已读取 {info.consumed_bytes} 字节"
            f"；未消费尾部 {len(info.unconsumed_data)} 字节"
        )
        lines.append("  原始字段、偏移、尾部字节：地图信息证据.json")
    if info.diagnostics:
        lines.append(f"W3I 诊断（{len(info.diagnostics)}）：")
        for diagnostic in info.diagnostics:
            lines.append(
                f"  [{diagnostic.code}] {diagnostic.field}"
                f" · 字节 {diagnostic.offset}：{diagnostic.message}"
            )
    elif info.parse_issue:
        lines.append(f"W3I 诊断：{info.parse_issue}")
    return lines


def _format_header(info: W3iInfo) -> list[str]:
    encoded = {record.name for record in info.fields}
    lines: list[str] = []
    for member in fields(info):
        name = member.name
        if name in _HEADER_HANDLED:
            continue
        value = getattr(info, name)
        if name not in encoded and (value is None or value == () or value == ""):
            continue
        label = _HEADER_LABELS.get(name, name)
        rendered = _header_value(name, value)
        if name in encoded and (value is None or value == ()):
            rendered = "未确认有效值（完整原值保留在证据 JSON）"
        lines.append(f"  {label}：{rendered}")
    if info.flags is not None or any(getattr(info, name) for name, _ in _FLAG_LABELS):
        lines.append(
            "  地图开关："
            + "；".join(
                f"{label}={'是' if getattr(info, name) else '否'}"
                for name, label in _FLAG_LABELS
            )
        )
    return ["\n地图设置：", *lines] if lines else []


def _header_value(name: str, value: object) -> str:
    if name == "game_data_set":
        labels = {-1: "未设置", 0: "按对战标志选择", 1: "自定义基础数据", 2: "对战数据"}
        return (
            f"{value}（{labels.get(value, '未知原值')}）"
            if isinstance(value, int)
            else _value(value)
        )
    if name == "game_data_version":
        labels = {0: "RoC", 1: "TFT", 2: "未设置"}
        return (
            f"{value}（{labels.get(value, '未知原值')}）"
            if isinstance(value, int)
            else _value(value)
        )
    if name in {"flags", "race_hud", "supported_modes"} and isinstance(value, int):
        return _mask(value)
    if name == "weather_id" and isinstance(value, str):
        return repr(value)
    return _value(value)


def _value(value: object) -> str:
    if value is None:
        return "未确认"
    if isinstance(value, tuple):
        return "(" + ", ".join(_value(item) for item in value) + ")"
    if value == "":
        return "(空)"
    return str(value)


def _mask(value: int | None) -> str:
    return "未编码" if value is None else f"{value} / 0x{value:08x}"


def _offset(start: int | None, end: int | None) -> str:
    return "" if start is None else f" · 字节 [{start}, {_value(end)})"


def _section(
    info: W3iInfo, name: str, label: str, count: int, complete: bool = True
) -> str:
    declared = next(
        (row.value for row in info.fields if row.name == name + ".count"), None
    )
    if declared is None:
        if name == "random_item_tables" and info.version in (18, 23):
            return f"\n{label}（该版本未编码此表）："
        state = "源表已省略" if info.optional_data_skipped else "声明数量未确认"
        return f"\n{label}（已保留 {count} 条；{state}）："
    state = "完整读取" if declared == count and complete else "部分读取"
    return f"\n{label}（声明 {declared} 条；已保留 {count} 条；{state}）："


def _format_players(info: W3iInfo) -> list[str]:
    if not info.players and not info.fields:
        return []
    lines = [_section(info, "players", "玩家", len(info.players))]
    for player in info.players:
        lines.append(
            f"  P{player.id + 1} {player.name or '(无名)'} · 原始 ID {player.id}"
            f" · {player.type_name}(type={player.type})"
            f" · {player.race_name}(race={player.race})"
            + _offset(player.offset, player.end_offset)
        )
        lines.append(
            f"    起点：X={_value(player.start_x)}，Y={_value(player.start_y)}"
            f"；玩家标志：{_mask(player.fixed_start)}"
            f"；种族界面：{_mask(player.race_hud)}"
        )
        lines.append(
            f"    同盟低/高优先级：{_mask(player.ally_low_priority_flags)}"
            f" / {_mask(player.ally_high_priority_flags)}"
            f"；敌人低/高优先级：{_mask(player.enemy_low_priority_flags)}"
            f" / {_mask(player.enemy_high_priority_flags)}"
        )
    return lines


def _format_forces(info: W3iInfo) -> list[str]:
    if not info.forces and not info.fields:
        return []
    lines = [_section(info, "forces", "队伍", len(info.forces))]
    for force in info.forces:
        members = "、".join(f"P{player}" for player in force.players) or "无"
        lines.append(
            f"  {force.name or '(无名队伍)'} · 玩家 {members}"
            f" · 原始标志 {_mask(force.flags)} · 玩家掩码 {_mask(force.player_mask)}"
            + _offset(force.offset, force.end_offset)
        )
        lines.append(
            "    "
            + "；".join(
                f"{name}={'是' if enabled else '否'}"
                for name, enabled in (
                    ("同盟", force.allied),
                    ("同盟胜利", force.allied_victory),
                    ("共享视野", force.share_vision),
                    ("共享控制", force.share_control),
                    ("共享高级控制", force.share_advanced_control),
                )
            )
        )
    return lines


def _format_tables(info: W3iInfo) -> list[str]:
    if not info.fields and not (
        info.upgrades
        or info.techs
        or info.random_unit_tables
        or info.random_item_tables
    ):
        return []
    lines: list[str] = []
    if info.optional_data_skipped:
        lines.append(
            "\n升级、科技、随机单位和物品表由 FF 标记省略；不能据此认定这些表为空。"
        )
    lines.append(_section(info, "upgrades", "升级可用性", len(info.upgrades)))
    for index, row in enumerate(info.upgrades, 1):
        lines.append(
            f"  #{index} ID={row.object_id!r} · 玩家掩码 {_mask(row.player_mask)}"
            f" · 等级原值 {row.level} · 可用性原值 {row.availability}"
            + _offset(row.offset, row.end_offset)
        )
    lines.append(_section(info, "techs", "科技可用性", len(info.techs)))
    for index, row in enumerate(info.techs, 1):
        lines.append(
            f"  #{index} ID={row.object_id!r} · 玩家掩码 {_mask(row.player_mask)}"
            + _offset(row.offset, row.end_offset)
        )
    lines.append(
        _section(
            info,
            "random_unit_tables",
            "随机单位表",
            len(info.random_unit_tables),
            all(row.complete for row in info.random_unit_tables),
        )
    )
    for table in info.random_unit_tables:
        lines.append(
            f"  表 {table.index} {table.name!r} · {'完整' if table.complete else '部分'}"
            + _offset(table.offset, table.end_offset)
        )
        lines.append(
            "    列类型原值："
            + ", ".join(
                f"#{index}={kind}" for index, kind in enumerate(table.column_types)
            )
        )
        for index, row in enumerate(table.rows, 1):
            lines.append(
                f"    行 #{index} · 概率原值 {row.chance} · 对象 "
                + ", ".join(
                    f"列{column}={code!r}" for column, code in enumerate(row.object_ids)
                )
                + _offset(row.offset, row.end_offset)
            )
    lines.append(
        _section(
            info,
            "random_item_tables",
            "随机物品表",
            len(info.random_item_tables),
            all(row.complete for row in info.random_item_tables),
        )
    )
    for table in info.random_item_tables:
        lines.append(
            f"  表 {table.index} {table.name!r} · {'完整' if table.complete else '部分'}"
            + _offset(table.offset, table.end_offset)
        )
        for index, group in enumerate(table.sets, 1):
            lines.append(
                f"    集合 #{index} · 已保留 {len(group.items)} 项"
                f" · {'完整' if group.complete else '部分'}"
                + _offset(group.offset, group.end_offset)
            )
            for item_index, item in enumerate(group.items, 1):
                lines.append(
                    f"      #{item_index} ID={item.object_id!r} · 概率原值 {item.chance}"
                    + _offset(item.offset, item.end_offset)
                )
    return lines
