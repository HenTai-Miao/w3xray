"""Text formatter for the map information page."""

from __future__ import annotations

from .api import MapData


def format_map_info(md: MapData | None) -> str:
    if md is None:
        return "此图无 war3map.w3i 地图信息（或解析失败）。"
    lines: list[str] = []
    w3f = md.w3f
    info = md.w3i
    if w3f:
        lines.extend(_format_campaign_info(w3f))
    if info:
        lines.extend(_format_w3i_info(info, md))
    lines.extend(_format_trigger_summary(md))
    lines.extend(_format_game_configs(md))
    lines.extend(_format_world_metadata(md))
    lines.extend(_format_preview_icons(md))
    lines.extend(_format_import_summary(md))
    if not lines:
        return "此图无 war3map.w3i 地图信息（或解析失败）。"
    return "\n".join(lines)


def _format_campaign_info(w3f) -> list[str]:
    lines = ["【战役信息】", f"战役名　：{w3f.name or '(未命名)'}"]
    if w3f.author:
        lines.append(f"作者　　：{w3f.author}")
    if w3f.difficulty:
        lines.append(f"难度　　：{w3f.difficulty}")
    if w3f.description:
        lines.append(f"描述　　：{w3f.description}")
    lines.append("")
    return lines


def _format_w3i_info(info, md: MapData) -> list[str]:
    lines = [
        f"地图名　：{info.map_name or '(未命名)'}",
        f"作者　　：{info.author or '(未知)'}",
    ]
    if info.recommended_players:
        lines.append(f"推荐人数：{info.recommended_players}")
    lines.append(f"尺寸　　：{info.width} × {info.height}")
    version_names = {18: "RoC(1.07-)", 25: "TFT(1.13-)", 28: "重制 1.31", 31: "重制 1.32+"}
    lines.append(f"格式版本：{info.version}  {version_names.get(info.version, '')}")
    if info.script_type:
        lines.append(f"脚本语言：{info.script_type}")
    tags = _map_tags(info)
    if tags:
        lines.append("标志　　：" + "、".join(tags))
    if md.script_features:
        lines.append("脚本特征：" + "、".join(md.script_features) + "  （脚本用到的暴雪内置机制）")
    if info.description:
        lines.append(f"\n描述：\n{info.description}")
    if info.players:
        lines.append(f"\n玩家（{len(info.players)}）：")
        for player in info.players:
            lines.append(
                f"  P{player.id + 1}  {player.name or '(无名)'}  ·  "
                f"{player.type_name}  ·  {player.race_name}"
            )
    if info.forces:
        lines.append(f"\n队伍（{len(info.forces)}）：")
        for force in info.forces:
            lines.append(_format_force(force))
    return lines


def _map_tags(info) -> list[str]:
    tags = []
    if info.melee:
        tags.append("对战图")
    if info.custom_forces:
        tags.append("自定义队伍")
    if info.custom_techtree:
        tags.append("自定义科技树")
    if info.custom_ability:
        tags.append("自定义技能")
    return tags


def _format_force(force) -> str:
    share = []
    if force.allied:
        share.append("同盟")
    if force.share_vision:
        share.append("共享视野")
    if force.share_control:
        share.append("共享控制")
    players = "、".join(f"P{i}" for i in force.players) if force.players else "无"
    suffix = f"  ·  {'/'.join(share)}" if share else ""
    return f"  {force.name or '(无名队伍)'}  ·  玩家 {players}{suffix}"


def _format_world_metadata(md: MapData) -> list[str]:
    lines = []
    if md.regions or md.cameras or md.sounds:
        lines.append(f"\n世界编辑器数据：区域 {len(md.regions)} · 镜头 {len(md.cameras)} · 声音 {len(md.sounds)}")
    if md.regions:
        lines.append(f"  区域：{_names([r.name or str(r.region_id) for r in md.regions])}")
    if md.cameras:
        lines.append(f"  镜头：{_names([c.name or '(未命名镜头)' for c in md.cameras])}")
    if md.sounds:
        imported = sum(1 for sound in md.sounds if sound.is_imported)
        music = sum(1 for sound in md.sounds if sound.is_music)
        lines.append(f"  声音：{_names([s.name or s.path for s in md.sounds])}"
                     f"  （导入 {imported}，音乐 {music}）")
    return lines


def _format_game_configs(md: MapData) -> list[str]:
    configs = getattr(md, "game_configs", None) or []
    if not configs:
        return []
    lines = [f"\n游戏配置：{len(configs)} 个"]
    for entry in configs[:4]:
        cfg = entry.config
        lines.append(
            f"  {entry.source}：{cfg.map_path or '(未指定地图)'}"
            f"  · 速度 {cfg.speed_label}"
            f"  · 玩家 {len(cfg.players)}"
        )
        rules = []
        if cfg.fog_of_war_disabled:
            rules.append("禁用战争迷雾")
        if cfg.victory_defeat_disabled:
            rules.append("禁用胜负条件")
        if rules:
            lines.append("    规则：" + "、".join(rules))
        custom_ai = [p for p in cfg.players if p.load_custom_ai and p.custom_ai_path]
        if custom_ai:
            names = [f"P{p.slot_id + 1}:{p.custom_ai_path}" for p in custom_ai]
            lines.append(f"    自定义AI：{_names(names, 4)}")
    if len(configs) > 4:
        lines.append(f"  ……另 {len(configs) - 4} 个配置")
    return lines


def _format_trigger_summary(md: MapData) -> list[str]:
    summary = getattr(md, "trigger_summary", None)
    if summary is None:
        return []
    kind = "重制版" if summary.is_reforged else "经典"
    lines = [
        f"\n触发器树：{kind} v{summary.version}"
        f"  · 触发器 {summary.trigger_count}"
        f"  · 变量 {summary.variable_count}"
        f"  · 分类 {summary.category_count}"
    ]
    if summary.comment_count or summary.script_count:
        lines.append(f"  注释：{summary.comment_count}  自定义脚本块：{summary.script_count}")
    if summary.categories:
        lines.append(f"  分类：{_names([cat.name for cat in summary.categories if cat.name])}")
    if summary.variables:
        lines.append(f"  变量：{_names([var.name for var in summary.variables if var.name])}")
    if summary.triggers:
        lines.append(f"  触发器：{_names([trigger.name or '(未命名触发器)' for trigger in summary.triggers])}")
    if summary.has_unexpanded_functions:
        lines.append("  ECA 函数体未展开：缺 TriggerData.txt 参数表，只显示触发器头。")
    return lines


def _format_preview_icons(md: MapData) -> list[str]:
    summary = getattr(md, "preview_icons", None)
    if summary is None:
        return []
    lines = [
        f"\n小地图标记：{summary.icon_count} 个"
        f"  · 玩家出生点 {summary.player_start_count}"
        f"  · 金矿 {summary.gold_mine_count}"
        f"  · 中立建筑 {summary.neutral_building_count}"
    ]
    if summary.icons:
        names = [f"{icon.type_label}({icon.x},{icon.y})" for icon in summary.icons]
        lines.append(f"  标记：{_names(names)}")
    return lines


def _format_import_summary(md: MapData) -> list[str]:
    summary = getattr(md, "import_summary", None)
    if summary is None:
        return []
    lines = [
        f"\n导入资源：{summary.entry_count} 个"
        f"  · 标准路径 {summary.standard_count}"
        f"  · 自定义路径 {summary.custom_count}"
    ]
    if summary.unknown_count:
        lines[0] += f"  · 未知标志 {summary.unknown_count}"
    if summary.extension_counts:
        ext_text = "、".join(f"{ext}:{count}" for ext, count in summary.extension_counts[:6])
        lines.append(f"  类型：{ext_text}")
    if summary.missing_paths:
        lines.append(f"  疑似缺失：{_names(list(summary.missing_paths), 6)}")
    else:
        lines.append(f"  已匹配文件：{len(summary.resolved_paths)}")
    return lines


def _names(names: list[str], limit: int = 8) -> str:
    shown = names[:limit]
    suffix = f" ……另 {len(names) - limit} 个" if len(names) > limit else ""
    return "、".join(shown) + suffix
