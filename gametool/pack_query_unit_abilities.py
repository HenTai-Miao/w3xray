"""Unit/hero declared skill links and complete category-qualified skill fields."""

from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass

from .object_codes import field_object_codes, encode_object_id_query
from .object_layers import split_field_column
from .pack_query_combat_evidence import render_combat_parameters
from .pack_query_field_evidence import ObjectField, ObjectFields


_ROLES = {"uabi": "默认技能", "uhab": "可学习英雄技能"}
_ALIASES = {"abilList": "uabi", "heroAbilList": "uhab"}


@dataclass(frozen=True, slots=True)
class UnitAbilityLink:
    role: str
    field: ObjectField
    codes: tuple[str, ...]
    selected: bool
    inherited: bool


@dataclass(frozen=True, slots=True)
class UnitAbilityEvidence:
    links: tuple[UnitAbilityLink, ...]
    abilities: tuple[ObjectFields, ...]
    ability_roles: tuple[tuple[str, ...], ...]
    search_values: tuple[tuple[str, ...], ...]
    diagnostics: tuple[str, ...] = ()
    fields_complete: bool = True

    def search_fields(self) -> Iterator[str]:
        for values in self.search_values:
            yield from values

    def render_lines(self, indent: str = "  ") -> tuple[str, ...]:
        if not self.links:
            return ()
        lines = [
            indent + "单位技能联查（仅静态声明；不证明已学习、当前持有或正在生效）:",
            indent
            + "  默认技能与可学习技能分别保留；仅展开可确认四码，完整链接原文见对象字段。",
        ]
        for link in self.links:
            state = (
                "已被自定义声明或对象层覆盖，未展开"
                if not link.selected
                else "继承声明"
                if link.inherited
                else "地图声明"
            )
            value = link.field.value or "（显式空值）"
            lines.append(
                f"{indent}  {_ROLES[link.role]} · {link.field.key} [{state}]: {value} [来源: {link.field.source or '来源未记录'}；状态: {link.field.state}]"
            )
        lines.extend(indent + "  " + note for note in self.diagnostics)
        for ability, roles in zip(self.abilities, self.ability_roles):
            names = " / ".join(ability.names)
            lines.append(
                f"{indent}  关联技能 [{ability.code}]"
                + (" " + names if names else "")
                + "（"
                + "、".join(roles)
                + "）"
            )
            if not ability.fields:
                lines.append(
                    f"{indent}    字段未记录；可用 skills {encode_object_id_query(ability.code)} / text {ability.code} 查证或重新导出。"
                )
                continue
            lines.extend(
                render_combat_parameters(
                    "技能",
                    ability.fields,
                    complete=self.fields_complete,
                    indent=indent + "    ",
                )
            )
            lines.append(indent + "    完整技能字段:")
            for field in ability.fields:
                lines.extend(field.render_lines(indent + "      "))
        return tuple(lines)


def unit_ability_evidence(
    fields: tuple[ObjectField, ...],
    abilities: Mapping[str, ObjectFields],
    clean: Callable[[str], str],
    *,
    fields_complete: bool = True,
    search_cache: dict[str, tuple[str, ...]] | None = None,
) -> UnitAbilityEvidence:
    """Resolve only declared links; empty/unknown custom declarations block bases."""
    grouped: dict[str, list[tuple[ObjectField, bool]]] = {}
    for field in fields:
        key = field.key
        inherited = key.casefold().startswith("base:")
        if inherited:
            key = key[5:]
        key, _column = split_field_column(key)
        role = key if key in _ROLES else _ALIASES.get(key)
        if role:
            grouped.setdefault(role, []).append((field, inherited))
    links: list[UnitAbilityLink] = []
    diagnostics: list[str] = []
    for role, rows in grouped.items():
        has_custom = any(not inherited for _field, inherited in rows)
        selected = tuple(
            field
            for field, inherited in rows
            if inherited != has_custom and field.active
        )
        if len({field.value for field in selected}) > 1:
            diagnostics.append(
                f"{_ROLES[role]}有多种声明，保留各来源的确认引用；不能据此认定同时生效。"
            )
        for field, inherited in rows:
            chosen = inherited != has_custom and field.active
            link_codes = (
                field_object_codes(field.value) if chosen and field.confirmed else ()
            )
            links.append(UnitAbilityLink(role, field, link_codes, chosen, inherited))
            if chosen and (
                not field.confirmed or field.value.strip() and not link_codes
            ):
                diagnostics.append(
                    f"{_ROLES[role]}字段 {field.key} 未确认可展开四码，保留原文；可用 text <词> 查证，未回退继承值。"
                )
    codes: dict[str, dict[str, None]] = {}
    for link in links:
        if link.selected:
            for code in link.codes:
                codes.setdefault(code, {}).setdefault(_ROLES[link.role], None)
    selected_abilities = tuple(
        abilities.get(code) or ObjectFields(code, (), ()) for code in codes
    )
    cache = {} if search_cache is None else search_cache
    search_values: list[tuple[str, ...]] = []
    for ability in selected_abilities:
        if ability.code not in cache:
            cache[ability.code] = (
                ability.code,
                *ability.names,
                *(
                    value
                    for field in ability.fields
                    for value in field.search_fields(clean)
                ),
            )
        search_values.append(cache[ability.code])
    return UnitAbilityEvidence(
        tuple(links),
        selected_abilities,
        tuple(tuple(roles) for roles in codes.values()),
        tuple(search_values),
        tuple(diagnostics),
        fields_complete,
    )
