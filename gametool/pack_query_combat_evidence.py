"""Static combat parameters from complete, category-qualified field evidence."""

from dataclasses import dataclass
from decimal import Decimal
import re

from .object_layers import split_field_column
from .pack_query_field_evidence import ObjectField
from .pack_query_numeric_values import decimal_value


# These are explicit object-editor field identities, not runtime layouts or
# plugin defaults. Unrecognized keys and labels remain in the full field view.
_SKILLS = {
    "acdn": ("冷却", "秒", True),
    "amcs": ("魔法消耗", "", True),
    "aran": ("施法距离", "", True),
    "aare": ("作用范围", "", True),
    "adur": ("持续时间", "秒", True),
    "ahdu": ("英雄持续时间", "秒", True),
    "acas": ("施法时间", "秒", True),
    "ahky": ("普通热键", "", False),
    "auhk": ("关闭热键", "", False),
    "arhk": ("学习热键", "", False),
}
_UNITS = {
    "ua1b": ("攻击 1 基础伤害", "", True),
    "ua1d": ("攻击 1 伤害骰子数", "", True),
    "ua1s": ("攻击 1 骰子面数", "", True),
    "ua1c": ("攻击 1 间隔", "秒", True),
    "ua1r": ("攻击 1 射程", "", True),
    "ua1t": ("攻击 1 类型", "", False),
    "ua2b": ("攻击 2 基础伤害", "", True),
    "ua2d": ("攻击 2 伤害骰子数", "", True),
    "ua2s": ("攻击 2 骰子面数", "", True),
    "ua2c": ("攻击 2 间隔", "秒", True),
    "ua2r": ("攻击 2 射程", "", True),
    "ua2t": ("攻击 2 类型", "", False),
    "udef": ("基础护甲", "", True),
    "udty": ("护甲类型", "", False),
    "umvs": ("移动速度", "", True),
    "usid": ("白天视野", "", True),
    "usin": ("夜晚视野", "", True),
}
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")


@dataclass(frozen=True, slots=True)
class CombatParameter:
    key: str
    label: str
    level: str
    column: str | None
    unit: str
    numeric: bool
    fields: tuple[ObjectField, ...]
    inherited: bool
    diagnostics: tuple[str, ...] = ()


def _field_identity(
    key: str, definitions: dict[str, tuple[str, str, bool]]
) -> tuple[str, str, str | None, bool] | None:
    inherited = key.casefold().startswith("base:")
    if inherited:
        key = key[5:]
    key, column = split_field_column(key)
    for prefix in definitions:
        if key == prefix:
            return prefix, "", column, inherited
        if key.startswith(prefix):
            level = key[len(prefix) :].removeprefix(":")
            if level and level.isascii() and level.isdecimal():
                # Identity normalization never converts a level to int or uses
                # it to allocate/enumerate levels. Raw keys remain on each row.
                return prefix, level.lstrip("0") or "0", column, inherited
    return None


def _value(field: ObjectField, numeric: bool) -> str | Decimal | None:
    if not field.confirmed:
        return None
    if not numeric:
        return field.value
    # TSV semantic cells have already been decoded. Do not strip a second
    # spreadsheet-safety envelope or accept literal quote-prefixed numbers.
    raw = field.value.strip()
    return decimal_value(raw) if _NUMBER.fullmatch(raw) else None


def combat_parameters(
    category: str, fields: tuple[ObjectField, ...], *, complete: bool = True
) -> tuple[CombatParameter, ...]:
    """Keep every encoded level/column; never synthesize absent levels or values."""
    definitions = (
        _SKILLS
        if category == "技能"
        else _UNITS
        if category in {"单位", "英雄"}
        else {}
    )
    grouped: dict[tuple[str, str, str | None], list[tuple[ObjectField, bool]]] = {}
    for field in fields:
        identity = _field_identity(field.key, definitions)
        if identity is not None:
            key, level, column, inherited = identity
            grouped.setdefault((key, level, column), []).append((field, inherited))
    result: list[CombatParameter] = []
    order = {key: index for index, key in enumerate(definitions)}
    for (key, level, column), rows in sorted(
        grouped.items(),
        key=lambda item: (
            len(item[0][1]),
            item[0][1],
            order[item[0][0]],
            item[0][2] is not None,
            len(item[0][2] or ""),
            item[0][2] or "",
        ),
    ):
        custom = tuple(field for field, inherited in rows if not inherited)
        inherited = not custom
        selected = tuple(
            field for field, is_base in rows if is_base == inherited and field.active
        )
        label, unit, numeric = definitions[key]
        notes: list[str] = []
        if not selected:
            # Overridden-only data remains in the original evidence section;
            # it cannot become a current value or unlock a base fallback.
            notes.append("只有已覆盖记录，当前值未确认；完整原文见对象字段。")
        else:
            values = tuple(_value(field, numeric) for field in selected)
            if any(value is None for value in values):
                notes.append("存在未确认状态或非有限数字，未选择其他记录或继承值。")
            if len(set(values)) > 1:
                notes.append("同一参数/等级/数据列有冲突，未选择单一生效值。")
        if inherited and not complete:
            notes.append("字段来源不完整，继承记录未判为当前值。")
        result.append(
            CombatParameter(
                key,
                label,
                level,
                column,
                unit,
                numeric,
                selected,
                inherited,
                tuple(notes),
            )
        )
    return tuple(result)


def render_combat_parameters(
    category: str,
    fields: tuple[ObjectField, ...],
    *,
    complete: bool = True,
    indent: str = "  ",
) -> tuple[str, ...]:
    parameters = combat_parameters(category, fields, complete=complete)
    if not parameters:
        return ()
    lines = [
        indent + "静态技能参数（逐级保留；不代表当前冷却或已学等级）:"
        if category == "技能"
        else indent + "静态战斗字段（不代表局内加成、当前攻防或实战 DPS）:"
    ]
    for parameter in parameters:
        context = (
            "等级 " + (parameter.level or "未记录")
            if category == "技能" or parameter.level
            else ""
        )
        if parameter.column is not None:
            context += ("，" if context else "") + "数据列 " + parameter.column
        context = f"（{context}）" if context else ""
        origin = "继承字段参考" if parameter.inherited else "地图字段"
        state = "；未确认" if parameter.diagnostics else ""
        lines.append(f"{indent}  {parameter.label}{context} [{origin}{state}]")
        for field in parameter.fields:
            value = field.value if field.value else "（显式空值）"
            suffix = (
                " " + parameter.unit
                if parameter.unit and _value(field, parameter.numeric) is not None
                else ""
            )
            lines.append(
                f"{indent}    {value}{suffix} [字段: {field.key}；来源: {field.source or '来源未记录'}；状态: {field.state}]"
            )
        lines.extend(indent + "    " + note for note in parameter.diagnostics)
    return tuple(lines)
