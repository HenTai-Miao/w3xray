"""Lossless linked-ability fields with small, source-qualified attribute summaries."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
import re

from .pack_query_objects import valid_object_code

_ATTRIBUTES = {"Istr": "力量", "Iagi": "敏捷", "Iint": "智力"}
_ATTRIBUTE = re.compile(r"(Istr|Iagi|Iint)(?::([0-9]+)|([0-9]+))?\Z")
_NUMBER = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?\Z")
_INHERITED_LINKS = {"base:iabi", "base:abillist", "base:技能"}


@dataclass(frozen=True, slots=True)
class AbilityField:
    key: str
    label: str
    value: str
    source: str
    extras: tuple[tuple[str, str], ...] = ()


@dataclass(frozen=True, slots=True)
class AbilityEvidence:
    code: str
    names: tuple[str, ...]
    fields: tuple[AbilityField, ...]


@dataclass(frozen=True, slots=True)
class AbilityLink:
    key: str
    value: str
    source: str
    codes: tuple[str, ...]


def _summaries(ability: AbilityEvidence) -> tuple[str, ...]:
    candidates: dict[tuple[str, str, str], str] = {}
    levels: dict[str, set[str]] = {}
    values: dict[tuple[str, str], set[str]] = {}
    for row in ability.fields:
        match = _ATTRIBUTE.fullmatch(row.key)
        if match is None:
            continue
        value = row.value.strip().lstrip("'").strip()
        if not _NUMBER.fullmatch(value):
            continue
        field = match.group(1)
        raw_level = match.group(2) or match.group(3) or ""
        level = raw_level.lstrip("0") or ("0" if raw_level else "")
        candidates.setdefault((field, level, value), row.key)
        levels.setdefault(field, set()).add(level)
        values.setdefault((field, level), set()).add(value)
    field_order = {field: index for index, field in enumerate(_ATTRIBUTES)}
    ordered = sorted(
        candidates, key=lambda key: (field_order[key[0]], len(key[1]), key[1])
    )
    output: list[str] = []
    for field, level, value in ordered:
        prefix = "" if value.startswith(("+", "-")) else "+"
        summary = prefix + value + " " + _ATTRIBUTES[field]
        if (
            level not in ("", "1")
            or len(levels[field]) > 1
            or len(values[field, level]) > 1
        ):
            summary += f"（技能 [{ability.code}]，等级 {level or '未记录'}，字段 {candidates[field, level, value]}）"
        output.append(summary)
    return tuple(output)


@dataclass(frozen=True, slots=True)
class ItemAbilityIndex:
    custom_links: dict[str, tuple[AbilityLink, ...]]
    inherited_links: dict[str, tuple[AbilityLink, ...]]
    abilities: dict[str, AbilityEvidence]
    ability_summaries: dict[str, tuple[str, ...]]

    @property
    def item_codes(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((*self.custom_links, *self.inherited_links)))

    def _selected_links(self, item: str) -> tuple[AbilityLink, ...]:
        return self.custom_links.get(item, self.inherited_links.get(item, ()))

    def abilities_for(self, item: str) -> tuple[AbilityEvidence, ...]:
        codes = dict.fromkeys(
            code for link in self._selected_links(item) for code in link.codes
        )
        return tuple(self.abilities[code] for code in codes)

    def summaries_for(self, item: str) -> tuple[str, ...]:
        abilities = self.abilities_for(item)
        ambiguous = len({link.value for link in self._selected_links(item)}) > 1
        output: list[str] = []
        for ability in abilities:
            for value in self.ability_summaries.get(ability.code, ()):
                if len(abilities) > 1 and f"技能 [{ability.code}]" not in value:
                    value += f"（技能 [{ability.code}]）"
                if ambiguous:
                    value += "（关联字段有多种取值）"
                output.append(value)
        return tuple(output)

    def render_item(self, item: str) -> tuple[str, ...]:
        selected = self._selected_links(item)
        inherited = (
            self.inherited_links.get(item, ()) if item in self.custom_links else ()
        )
        if not selected and not inherited:
            return ()
        lines: list[str] = []
        if len({link.value for link in selected}) > 1:
            lines.append("  物品技能字段有多种取值，以下保留各记录及其来源。")
        for overridden, links in ((False, selected), (True, inherited)):
            for link in links:
                tag = (
                    "（已被自定义 iabi 覆盖的继承字段）"
                    if overridden
                    else "（继承字段）"
                    if link.key.casefold().startswith("base:")
                    else ""
                )
                lines.append(
                    f"  物品技能字段 {link.key}{tag}: {link.value or '（显式空值）'}  [来源: {link.source or '来源未记录'}]"
                )
                if not overridden and link.value.strip() and not link.codes:
                    lines.append(
                        f"    未识别静态四码，保留原文；可用 doc {item} / text {item} 继续查证。"
                    )
        abilities = self.abilities_for(item)
        if abilities:
            lines.append("  以下为携带技能静态字段，按技能与等级分别保留。")
        for ability in abilities:
            names = " / ".join(ability.names)
            lines.append(
                f"  关联技能 [{ability.code}]" + (" " + names if names else "")
            )
            if not ability.fields:
                lines.append(
                    f"    字段未记录；可用 skills {ability.code} / doc {ability.code} / text {ability.code} 查证或重新导出。"
                )
                continue
            for row in ability.fields:
                key = row.key or "（字段键未记录）"
                label = " / " + row.label if row.label and row.label != row.key else ""
                inherited_tag = (
                    "（继承字段原文）" if row.key.casefold().startswith("base:") else ""
                )
                lines.append(
                    f"    {key}{label}{inherited_tag}: {row.value or '（显式空值）'}  [来源: {row.source or '来源未记录'}]"
                )
                lines.extend(
                    f"      {label}: {value or '（显式空值）'}"
                    for label, value in row.extras
                )
        return tuple(lines)


def item_ability_index(
    rows: tuple[tuple[str, ...], ...],
    decode_codes: Callable[[str], Sequence[str]],
    clean: Callable[[str], str],
) -> ItemAbilityIndex:
    custom: dict[str, dict[AbilityLink, None]] = {}
    inherited: dict[str, dict[AbilityLink, None]] = {}
    fields: dict[str, dict[AbilityField, None]] = {}
    names: dict[str, dict[str, None]] = {}
    referenced: dict[str, None] = {}
    header = rows[0] if rows else ()
    for row in rows[1:]:
        if len(row) < 7 or not valid_object_code(row[1]):
            continue
        if row[0] == "物品" and (
            row[3] == "iabi" or row[3].casefold() in _INHERITED_LINKS
        ):
            link = AbilityLink(row[3], row[5], row[6], tuple(decode_codes(row[5])))
            target = custom if row[3] == "iabi" else inherited
            target.setdefault(row[1], {}).setdefault(link, None)
            for code in link.codes:
                referenced.setdefault(code, None)
        elif row[0] == "技能":
            extras = tuple(
                (
                    header[index] if index < len(header) else f"扩展字段{index + 1}",
                    value,
                )
                for index, value in enumerate(row[7:], 7)
            )
            fields.setdefault(row[1], {}).setdefault(
                AbilityField(row[3], clean(row[4]), row[5], row[6], extras), None
            )
            if name := clean(row[2]):
                names.setdefault(row[1], {}).setdefault(name, None)
    codes = dict.fromkeys((*fields, *referenced))
    abilities = {
        code: AbilityEvidence(
            code, tuple(names.get(code, ())), tuple(fields.get(code, ()))
        )
        for code in codes
    }
    return ItemAbilityIndex(
        {code: tuple(links) for code, links in custom.items()},
        {code: tuple(links) for code, links in inherited.items()},
        abilities,
        {
            code: values
            for code, ability in abilities.items()
            if (values := _summaries(ability))
        },
    )
