"""CLI summaries for embedded and standalone game configurations."""

from __future__ import annotations

from collections.abc import Iterator
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import MapData
    from .gameconfig import GameConfiguration, GameConfigPlayer


def iter_game_config_summary_lines(
    source: str,
    config: GameConfiguration,
) -> Iterator[str]:
    """Render a standalone .wgc file summary."""
    yield f"游戏配置: {source}"
    yield f"  地图路径: {config.map_path or '(未指定)'}"
    yield f"  速度: {config.speed_label}  玩家槽: {len(config.players)}"
    rule_tags = _game_config_rule_tags(config)
    if rule_tags:
        yield f"  规则: {'、'.join(rule_tags)}"
    yield (
        f"  用户: {config.human_count}  电脑: {config.computer_count}"
        f"  观察者: {config.observer_count}"
    )
    for player in config.players[:12]:
        yield "    - " + _format_game_config_player(player)
    if len(config.players) > 12:
        yield f"    …… 另有 {len(config.players) - 12} 个玩家槽"


def iter_embedded_game_config_summary_lines(md: MapData) -> Iterator[str]:
    """Render game configurations discovered inside a loaded map."""
    configs = getattr(md, "game_configs", None) or []
    if not configs:
        return
    yield "  游戏配置:"
    for entry in configs[:4]:
        config = entry.config
        yield (
            f"    - {entry.source}: {config.map_path or '(未指定地图)'}"
            f"  速度: {config.speed_label}  玩家槽: {len(config.players)}"
        )
        rule_tags = _game_config_rule_tags(config)
        if rule_tags:
            yield f"      规则: {'、'.join(rule_tags)}"
        ai_players = [
            player
            for player in config.players
            if player.load_custom_ai and player.custom_ai_path
        ]
        for player in ai_players[:3]:
            yield f"      自定义AI: P{player.slot_id + 1} {player.custom_ai_path}"
        if len(ai_players) > 3:
            yield f"      …… 另有 {len(ai_players) - 3} 个自定义AI"
    if len(configs) > 4:
        yield f"    …… 另有 {len(configs) - 4} 个配置"


def _game_config_rule_tags(config: GameConfiguration) -> list[str]:
    tags: list[str] = []
    if config.fog_of_war_disabled:
        tags.append("禁用战争迷雾")
    if config.victory_defeat_disabled:
        tags.append("禁用胜负条件")
    return tags


def _format_game_config_player(player: GameConfigPlayer) -> str:
    parts = [
        f"P{player.slot_id + 1}",
        player.kind_label,
        f"队伍{player.team + 1}",
        player.race_label,
        player.color_label,
        f"让分{player.handicap}%",
    ]
    if not player.is_user and not player.is_observer:
        parts.append(f"AI:{player.ai_difficulty_label}")
    if player.load_custom_ai and player.custom_ai_path:
        path_kind = "绝对" if player.ai_path_is_absolute else "相对"
        parts.append(f"自定义AI({path_kind}):{player.custom_ai_path}")
    return "  ".join(parts)
