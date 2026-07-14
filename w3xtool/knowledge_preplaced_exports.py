"""Preplaced unit and doodad TSV exports for knowledge packs."""

from __future__ import annotations

from .api import MapData
from .base_names import BASE_NAMES
from .doo import Doodad, Unit
from .doo_drops import DropSet
from .knowledge_io import tsv


def format_preplaced_units_tsv(md: MapData) -> str:
    """Return parsed war3mapUnits.doo placements as TSV."""
    rows = ["序号\t类型ID\t名称\t玩家\tX\tY\tZ\t角度\t生命\t魔法\t金矿\t英雄等级\t物品栏\t技能\t掉落"]
    for unit in md.units:
        rows.append("\t".join((
            str(unit.serial),
            tsv(unit.type_id),
            tsv(_code_name(md, unit.type_id)),
            str(unit.player),
            _num(unit.x),
            _num(unit.y),
            _num(unit.z),
            _num(unit.angle),
            str(unit.hp),
            str(unit.mana),
            str(unit.gold),
            str(unit.hero_level),
            tsv(_format_unit_items(md, unit)),
            tsv(_format_unit_abilities(md, unit)),
            tsv(_format_drop_sets(md, unit.drop_sets)),
        )))
    return "\n".join(rows) + "\n"


def format_preplaced_doodads_tsv(md: MapData) -> str:
    """Return parsed war3map.doo doodad/destructable placements as TSV."""
    rows = ["序号\t类型ID\t名称\tX\tY\tZ\t角度\t缩放\t状态\t生命\t掉落"]
    for doodad in md.doodads:
        rows.append("\t".join((
            str(doodad.serial),
            tsv(doodad.type_id),
            tsv(_code_name(md, doodad.type_id)),
            _num(doodad.x),
            _num(doodad.y),
            _num(doodad.z),
            _num(doodad.angle),
            tsv(_format_scale(doodad)),
            str(doodad.flags),
            str(doodad.life),
            tsv(_format_drops(md, doodad)),
        )))
    return "\n".join(rows) + "\n"


def _code_name(md: MapData, code: str) -> str:
    if code in md.obj_index:
        return str(md.obj_index[code].name)
    return BASE_NAMES.get(code) or code


def _format_unit_items(md: MapData, unit: Unit) -> str:
    return "; ".join(f"{slot}:{_code_label(md, item_id)}" for slot, item_id in unit.items)


def _format_unit_abilities(md: MapData, unit: Unit) -> str:
    return "; ".join(
        f"{_code_label(md, ability_id)}:{_active_label(active)}:{level}"
        for ability_id, active, level in unit.abilities
    )


def _format_drops(md: MapData, doodad: Doodad) -> str:
    if doodad.drop_sets:
        return _format_drop_sets(md, doodad.drop_sets)
    return "; ".join(f"{_code_label(md, item_id)}:{chance}%" for item_id, chance in doodad.drops)


def _format_drop_sets(md: MapData, drop_sets: tuple[DropSet, ...]) -> str:
    return "；".join(
        f"组{group.group_index + 1}["
        + "; ".join(
            f"{_code_label(md, entry.item_id)}:{entry.chance}%"
            for entry in group.entries
        )
        + "]"
        for group in drop_sets
    )


def _format_scale(doodad: Doodad) -> str:
    return ",".join(_num(value) for value in doodad.scale)


def _code_label(md: MapData, code: str) -> str:
    return f"{code}({_code_name(md, code)})"


def _active_label(active: int) -> str:
    return "启用" if active else "禁用"


def _num(value: float) -> str:
    if value == int(value):
        return str(int(value))
    return f"{value:.4g}"
