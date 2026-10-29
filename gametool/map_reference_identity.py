"""Retain declared object identities without adopting materialization defaults."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
import hashlib
import base64
import struct

from .campaign_sources import open_map_source
from .object_layers import binary_field_key, binary_field_label, binary_layer_priority
from .map_data import MapData
from .object_codes import valid_object_code
from .reference_models import ReferenceSource
from .w3obj import EXT_CATEGORY, parse_object_data_report


@dataclass(frozen=True, slots=True)
class MapBinaryField:
    key: str
    label: str
    value: str
    member: str
    storage_type: int
    level: int
    object_ordinal: int
    field_ordinal: int
    data_pointer: int = 0
    offset: int = -1
    end_offset: int = -1
    raw_bytes_base64: str = ""
    trailer: int = 0
    extra_ints: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class MapObjectIdentity:
    base_id: str = ""
    custom: str = ""
    declarations: tuple[tuple[str, str, str, int], ...] = ()
    diagnostics: tuple[str, ...] = ()
    binary_fields: tuple[MapBinaryField, ...] = ()


def map_object_identities(
    md: MapData,
    scope: str,
    members: Mapping[str, str],
    sources: Mapping[str, ReferenceSource],
    check: Callable[[], None],
) -> tuple[dict[tuple[str, str], MapObjectIdentity], tuple[str, ...]]:
    """Reuse the existing binary parser over ledger-bound members, once per scope.

    MapData's base/custom defaults for SLK/text/script candidates are display
    conveniences. Only unique explicit binary declarations establish these roles.
    """
    declarations: dict[tuple[str, str], list[tuple[str, str, str, int]]] = {}
    binary_fields: dict[tuple[str, str], list[MapBinaryField]] = {}
    diagnostics: list[str] = []
    try:
        with open_map_source(md) as archive:
            for prefix in (
                "war3map",
                "war3mapSkin",
                "war3campaign",
                "war3campaignSkin",
            ):
                for ext, category in EXT_CATEGORY.items():
                    check()
                    member = f"{prefix}.{ext}"
                    if not archive.has_file(member):
                        continue
                    try:
                        payload = archive.read_file(member)
                        source_id = members.get(member.casefold())
                        source = sources.get(source_id) if source_id else None
                        if (
                            source is None
                            or hashlib.sha256(payload).hexdigest() != source.sha256
                        ):
                            diagnostics.append(
                                f"{scope}!{member}: 身份声明成员未与提取台账摘要一致绑定；未猜测基础ID/自定义标记。"
                            )
                            continue
                        report = parse_object_data_report(payload, ext)
                        diagnostics.extend(
                            f"{scope}!{member}: 对象身份来源不完整: {issue}"
                            for issue in report.issues
                        )
                        for ordinal, obj in enumerate(report.objects, 1):
                            code = (
                                obj.new_id
                                if obj.is_custom and obj.new_id.strip("\0")
                                else obj.old_id
                            )
                            if not valid_object_code(code):
                                continue
                            declarations.setdefault((category, code), []).append(
                                (
                                    obj.old_id,
                                    "是" if obj.is_custom else "否",
                                    source.id,
                                    ordinal,
                                )
                            )
                            for field_ordinal, mod in enumerate(obj.mods, 1):
                                pointer = getattr(mod, "data_pointer", 0)
                                key = binary_field_key(mod.field_id, mod.level, pointer)
                                label = binary_field_label(
                                    mod.field_id, mod.level, pointer
                                )
                                binary_fields.setdefault((category, code), []).append(
                                    MapBinaryField(
                                        key,
                                        label,
                                        str(mod.value),
                                        member,
                                        mod.var_type,
                                        mod.level,
                                        ordinal,
                                        field_ordinal,
                                        pointer,
                                        getattr(mod, "offset", -1),
                                        getattr(mod, "end_offset", -1),
                                        base64.b64encode(
                                            getattr(mod, "raw_bytes", b"")
                                        ).decode("ascii"),
                                        getattr(mod, "trailer", 0),
                                        getattr(obj, "extra_ints", ()),
                                    )
                                )
                    except (
                        OSError,
                        ValueError,
                        KeyError,
                        IndexError,
                        struct.error,
                    ) as exc:
                        diagnostics.append(
                            f"{scope}!{member}: 身份声明读取失败: {type(exc).__name__}: {exc}"
                        )
    except OSError as exc:
        diagnostics.append(f"{scope}: 身份声明来源无法重开: {exc}")
    result = {}
    for identity, rows in declarations.items():
        highest = max(
            binary_layer_priority(source) for _base, _custom, source, _ordinal in rows
        )
        current = [row for row in rows if binary_layer_priority(row[2]) == highest]
        pairs = {(base, custom) for base, custom, _source, _ordinal in current}
        notes: tuple[str, ...] = ()
        base_id, custom = "", ""
        if len(pairs) == 1 and valid_object_code(current[0][0]):
            base_id, custom = current[0][:2]
        else:
            notes = (
                f"{scope} {identity[0]}:{identity[1]}: 基础ID/自定义声明冲突或无效；全部候选保留，未选任一声明。",
            )
            diagnostics.extend(notes)
        result[identity] = MapObjectIdentity(
            base_id, custom, tuple(rows), notes, tuple(binary_fields.get(identity, ()))
        )
    return result, tuple(diagnostics)
