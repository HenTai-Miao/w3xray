"""Typed, attributable field readings from an already captured memory snapshot.

The reader is a structural read-only interface. No process is opened, no game
code is called, and no default HP/MP/item-charge or Reforged offset is supplied.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from typing import Any, Protocol

from .live_profile_validation import (
    FIELD_QUALIFICATIONS,
    FIELD_SCOPES,
    LiveFieldLayout,
    field_layout_to_dict,
    parse_field_layouts,
    strict_integer,
)

__all__ = (
    "LiveFieldEvidence",
    "LiveFieldLayout",
    "SnapshotReader",
    "extract_item_fields",
    "extract_layout_fields",
    "extract_resource_fields",
    "extract_unit_fields",
    "observed_field",
    "read_item_fields",
    "reconcile_field_evidence",
)

_FORMATS: dict[str, str] = {
    "u8": "<B",
    "u16": "<H",
    "u32": "<I",
    "u64": "<Q",
    "i8": "<b",
    "i16": "<h",
    "i32": "<i",
    "i64": "<q",
    "f32": "<f",
    "f64": "<d",
    "fourcc": "<I",
}
_STATES = frozenset(
    {
        "confirmed",
        "unknown",
        "unavailable",
        "invalid",
        "conflict",
        "declared-layout-only",
    }
)


class SnapshotReader(Protocol):
    """A read must return exactly the requested bytes or explicit absence."""

    def read(self, addr: int, size: int) -> bytes | None: ...


@dataclass(frozen=True, slots=True)
class LiveFieldEvidence:
    """One field value, its qualification, and every byte-reading diagnostic."""

    key: str
    label: str
    value: int | float | str | None
    value_type: str
    state: str
    source: str
    address: int | None
    diagnostics: tuple[str, ...] = ()
    scope: str = ""
    build: str = ""
    profile: str = ""
    raw_bytes: str | None = None
    pointer_addresses: tuple[int, ...] = ()

    @property
    def complete(self) -> bool:
        return self.state == "confirmed" and not self.diagnostics

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "label": self.label,
            "value": self.value,
            "value_type": self.value_type,
            "state": self.state,
            "source": self.source,
            "address": self.address,
            "diagnostics": list(self.diagnostics),
            "scope": self.scope,
            "build": self.build,
            "profile": self.profile,
            "raw_bytes": self.raw_bytes,
            "pointer_addresses": list(self.pointer_addresses),
            "complete": self.complete,
        }


def _pointer_size(value: int) -> int:
    width = strict_integer(value, "pointer_size", minimum=4, maximum=8)
    if width not in (4, 8):
        raise ValueError("pointer_size 需要 4 或 8 字节")
    return width


def _qualification(value: str) -> str:
    if value not in FIELD_QUALIFICATIONS:
        raise ValueError("qualification 需要 confirmed 或 declared-layout-only")
    return value


def _address_error(address: object, size: int, pointer_size: int) -> str | None:
    if isinstance(address, bool) or not isinstance(address, int):
        return "地址不是严格整数"
    maximum = (1 << (pointer_size * 8)) - 1
    if address <= 0:
        return "地址为空或为负数"
    if address > maximum or size - 1 > maximum - address:
        return "字段字节跨出所声明架构的地址空间"
    return None


def _exact_read(
    reader: SnapshotReader, address: int, size: int, pointer_size: int
) -> tuple[bytes | None, str, tuple[str, ...]]:
    invalid = _address_error(address, size, pointer_size)
    if invalid:
        return None, "invalid", (invalid,)
    try:
        raw = reader.read(address, size)
    except Exception as error:
        return (
            None,
            "unavailable",
            (f"快照读取 0x{address:X}+{size} 失败: {type(error).__name__}: {error}",),
        )
    if raw is None:
        return None, "unavailable", (f"快照未覆盖 0x{address:X}+{size} 的全部字节",)
    if not isinstance(raw, bytes):
        return None, "invalid", (f"快照读取器返回非 bytes: {type(raw).__name__}",)
    if len(raw) != size:
        return (
            raw,
            "unavailable",
            (f"快照在 0x{address:X} 仅返回 {len(raw)}/{size} 字节",),
        )
    return raw, "confirmed", ()


def observed_field(
    *,
    key: str,
    label: str,
    value: int | float | str | None,
    value_type: str,
    source: str,
    address: int | None = None,
    state: str = "confirmed",
    diagnostics: Sequence[str] = (),
    scope: str = "",
    build: str = "",
    profile: str = "",
) -> LiveFieldEvidence:
    """Wrap an independently observed value without inventing missing bytes.

    This is for traversal identities/slot indices and already calibrated
    resource values, not a replacement for reading fields through the extractor.
    Declared f32/f64 values must encode as finite values of that width. This
    check never rounds or replaces the independently supplied observation.
    """
    if state not in _STATES:
        raise ValueError(f"不支持的字段状态: {state!r}")
    notes = list(diagnostics)
    invalid = _value_error(value, value_type) if value is not None else None
    if invalid:
        value = None
        state = "invalid"
        notes.append(invalid)
    if address is not None and (
        isinstance(address, bool) or not isinstance(address, int) or address <= 0
    ):
        address = None
        state = "invalid"
        notes.append("字段出处地址需要正整数")
    if value is None and state in FIELD_QUALIFICATIONS:
        state = "unavailable"
        notes.append("没有已读取的字段值")
    return LiveFieldEvidence(
        key,
        label,
        value,
        value_type,
        state,
        source,
        address,
        tuple(notes),
        scope,
        build,
        profile,
    )


def _value_error(value: object, value_type: str) -> str | None:
    if isinstance(value, bool):
        return "布尔值不构成已读取的数值证据"
    if (
        value_type in {"integer", "pointer"}
        or value_type in _FORMATS
        and value_type[0] in "ui"
    ):
        if not isinstance(value, int):
            return f"{value_type} 字段需要严格整数"
        if value_type == "integer":
            return None
        signed = value_type.startswith("i")
        bits = 64 if value_type == "pointer" else int(value_type[1:])
        lower = -(1 << (bits - 1)) if signed else 0
        upper = (1 << (bits - int(signed))) - 1
        if not lower <= value <= upper:
            return f"{value_type} 值超出编码范围"
        return None
    if value_type in {"f32", "f64", "float", "number"}:
        if not isinstance(value, (int, float)):
            return f"{value_type} 字段需要数值"
        if isinstance(value, float) and not math.isfinite(value):
            return "非有限数值不是有效运行时字段"
        if value_type in {"f32", "f64"}:
            fmt = _FORMATS[value_type]
            try:
                encoded = struct.pack(fmt, value)
            except OverflowError, struct.error:
                return f"{value_type} 值超出有限浮点编码范围"
            if not math.isfinite(struct.unpack(fmt, encoded)[0]):
                return f"{value_type} 值超出有限浮点编码范围"
        return None
    if value_type == "fourcc":
        if (
            not isinstance(value, str)
            or len(value) != 4
            or any(ord(c) > 255 for c in value)
        ):
            return "fourcc 字段需要完整四字节 Latin-1 身份"
        return None
    if value_type in {"string", "text"}:
        return None if isinstance(value, str) else "文本字段需要字符串"
    return f"未支持字段类型 {value_type!r}；未将未知语义确认为有效值"


def _extract_field(
    reader: SnapshotReader,
    base_address: int,
    layout: LiveFieldLayout,
    *,
    build: str,
    profile: str,
    pointer_size: int,
    qualification: str,
) -> LiveFieldEvidence:
    result = LiveFieldEvidence(
        layout.key,
        layout.label or layout.key,
        None,
        layout.value_type,
        "unavailable",
        layout.source,
        None,
        scope=layout.scope,
        build=build,
        profile=profile,
    )
    invalid = _address_error(base_address, 1, pointer_size)
    if invalid:
        return replace(result, state="invalid", diagnostics=(invalid,))
    offsets = (layout.offset,) if layout.offset is not None else layout.pointer_offsets
    current = base_address
    witnesses: list[int] = []
    for index, offset in enumerate(offsets[:-1]):
        address = current + offset
        witnesses.append(address)
        raw, state, notes = _exact_read(reader, address, pointer_size, pointer_size)
        if state != "confirmed" or raw is None:
            return replace(
                result,
                state=state,
                address=address,
                diagnostics=(f"指针链第 {index + 1} 跳不可用", *notes),
                raw_bytes=raw.hex() if raw is not None else None,
                pointer_addresses=tuple(witnesses),
            )
        current = int.from_bytes(raw, "little")
        if current == 0:
            return replace(
                result,
                state="unavailable",
                address=address,
                diagnostics=(f"指针链第 {index + 1} 跳为 NULL",),
                raw_bytes=raw.hex(),
                pointer_addresses=tuple(witnesses),
            )
    address = current + offsets[-1]
    fmt = "<I" if pointer_size == 4 else "<Q"
    if layout.value_type != "pointer":
        fmt = _FORMATS[layout.value_type]
    raw, state, notes = _exact_read(reader, address, struct.calcsize(fmt), pointer_size)
    result = replace(
        result,
        address=address,
        state=state,
        diagnostics=notes,
        raw_bytes=raw.hex() if raw is not None else None,
        pointer_addresses=tuple(witnesses),
    )
    if state != "confirmed" or raw is None:
        return result
    unpacked: int | float = struct.unpack(fmt, raw)[0]
    value: int | float | str = unpacked
    if layout.value_type == "fourcc":
        value = int.from_bytes(raw, "little").to_bytes(4, "big").decode("latin-1")
    if isinstance(value, float) and not math.isfinite(value):
        return replace(result, state="invalid", diagnostics=("字段为 NaN 或无穷值",))
    state = (
        "confirmed"
        if layout.evidence == qualification == "confirmed"
        else "declared-layout-only"
    )
    notes = ()
    if state != "confirmed":
        notes = ("字节读取成功；字段语义或当前 build 布局仍仅为声明，未独立核验。",)
    return replace(result, value=value, state=state, diagnostics=notes)


def reconcile_field_evidence(
    fields: Sequence[LiveFieldEvidence],
) -> list[LiveFieldEvidence]:
    """Reconcile all channels for one resolved subject, retaining every row.

    The caller combines builtin and declared reads for the same object/root
    before deriving a confirmed coordinate/owner. Different objects must be
    reconciled independently. Conflicts change qualification only: values,
    bytes, ordering, sources and previous diagnostics remain intact. Repeated
    reconciliation neither mutates inputs nor multiplies the same diagnostic.
    """
    reconciled = list(fields)
    groups: dict[tuple[str, str], list[int]] = {}
    for index, evidence in enumerate(reconciled):
        groups.setdefault((evidence.scope, evidence.key), []).append(index)
    for indexes in groups.values():
        usable = [index for index in indexes if reconciled[index].value is not None]
        identities = {
            (reconciled[index].value_type, reconciled[index].value) for index in usable
        }
        if len(identities) <= 1:
            continue
        diagnostic = (
            f"同名字段有 {len(identities)} 组冲突读数；保留全部来源，不选取单一值。"
        )
        for index in indexes:
            evidence = reconciled[index]
            notes = evidence.diagnostics
            if diagnostic not in notes:
                notes = (*notes, diagnostic)
            reconciled[index] = replace(
                evidence,
                state="conflict",
                diagnostics=notes,
            )
    return reconciled


def extract_layout_fields(
    reader: SnapshotReader,
    base_address: int,
    layouts: Sequence[LiveFieldLayout],
    *,
    scope: str,
    build: str,
    profile: str,
    pointer_size: int,
    qualification: str = "declared-layout-only",
) -> list[LiveFieldEvidence]:
    """Read every matching recipe, proving all pointer/value bytes in snapshot.

    A profile's ``evidence=confirmed`` is insufficient by itself: the caller
    must separately qualify the matched process/layout as ``confirmed``.
    """
    width = _pointer_size(pointer_size)
    _qualification(qualification)
    if scope not in FIELD_SCOPES:
        raise ValueError(f"不支持的字段 scope: {scope!r}")
    # Revalidate even manually constructed dataclasses before any read.
    validated = parse_field_layouts(
        [field_layout_to_dict(layout) for layout in layouts],
        arch="x86" if width == 4 else "x64",
    )
    return reconcile_field_evidence(
        [
            _extract_field(
                reader,
                base_address,
                layout,
                build=build,
                profile=profile,
                pointer_size=width,
                qualification=qualification,
            )
            for layout in validated
            if layout.scope == scope
        ]
    )


def _identity_field(
    address: int,
    *,
    scope: str,
    build: str,
    profile: str,
    source: str,
    qualification: str,
    pointer_size: int,
) -> LiveFieldEvidence:
    invalid = _address_error(address, 1, pointer_size)
    return observed_field(
        key="address",
        label="对象地址",
        value=address if invalid is None else None,
        value_type="pointer",
        source=source,
        address=address if invalid is None else None,
        state="invalid" if invalid else qualification,
        diagnostics=(invalid,) if invalid else (),
        scope=scope,
        build=build,
        profile=profile,
    )


def extract_unit_fields(
    reader: SnapshotReader,
    unit_addr: int,
    *,
    offsets: Mapping[str, int],
    build: str,
    profile: str,
    source: str,
    qualification: str = "confirmed",
    pointer_size: int = 4,
) -> list[LiveFieldEvidence]:
    """Read supplied proved code/owner/XY offsets, without fallback coordinates."""
    _pointer_size(pointer_size)
    _qualification(qualification)
    unknown = offsets.keys() - {"code", "owner", "x", "y"}
    if unknown:
        raise ValueError(f"未知单位字段偏移: {sorted(unknown)}")
    fields = [
        _identity_field(
            unit_addr,
            scope="unit",
            build=build,
            profile=profile,
            source=source,
            qualification=qualification,
            pointer_size=pointer_size,
        )
    ]
    for key, label, value_type in (
        ("code", "类型四码", "fourcc"),
        ("owner", "所属玩家槽", "u8"),
        ("x", "X 坐标", "f32"),
        ("y", "Y 坐标", "f32"),
    ):
        if key not in offsets:
            fields.append(
                observed_field(
                    key=key,
                    label=label,
                    value=None,
                    value_type=value_type,
                    source=source,
                    state="unavailable",
                    diagnostics=("当前 build 未提供已验证字段偏移",),
                    scope="unit",
                    build=build,
                    profile=profile,
                )
            )
            continue
        evidence = extract_layout_fields(
            reader,
            unit_addr,
            [
                LiveFieldLayout(
                    "unit",
                    key,
                    value_type,
                    source,
                    "confirmed",
                    offsets[key],
                    label=label,
                )
            ],
            scope="unit",
            build=build,
            profile=profile,
            pointer_size=pointer_size,
            qualification=qualification,
        )[0]
        if key == "owner" and isinstance(evidence.value, int) and evidence.value > 15:
            evidence = replace(
                evidence,
                state="invalid",
                diagnostics=(
                    *evidence.diagnostics,
                    "所属槽值超出当前经典布局声明的 0..15",
                ),
            )
        fields.append(evidence)
    return fields


def extract_item_fields(
    reader: SnapshotReader,
    item_addr: int,
    *,
    code_offset: int,
    slot: int | None = None,
    slot_address: int | None = None,
    build: str,
    profile: str,
    source: str,
    qualification: str = "confirmed",
    pointer_size: int = 4,
) -> list[LiveFieldEvidence]:
    """Preserve a resolved item's address/code and independently traversed slot."""
    fields = [
        _identity_field(
            item_addr,
            scope="item",
            build=build,
            profile=profile,
            source=source,
            qualification=_qualification(qualification),
            pointer_size=_pointer_size(pointer_size),
        ),
        *extract_layout_fields(
            reader,
            item_addr,
            [
                LiveFieldLayout(
                    "item",
                    "code",
                    "fourcc",
                    source,
                    "confirmed",
                    code_offset,
                    label="物品四码",
                )
            ],
            scope="item",
            build=build,
            profile=profile,
            pointer_size=pointer_size,
            qualification=qualification,
        ),
    ]
    invalid = slot is not None and (
        isinstance(slot, bool) or not isinstance(slot, int) or slot < 0
    )
    notes = ["槽位需要非负严格整数"] if invalid else []
    address_error = (
        _address_error(slot_address, 1, pointer_size)
        if slot_address is not None
        else None
    )
    if address_error:
        notes.append(f"槽位出处地址无效: {address_error}")
    fields.append(
        observed_field(
            key="slot",
            label="背包槽位",
            value=None if invalid else slot,
            value_type="integer",
            source=source,
            address=slot_address,
            state="invalid" if invalid or address_error else qualification,
            diagnostics=notes,
            scope="item",
            build=build,
            profile=profile,
        )
    )
    return fields


read_item_fields = extract_item_fields


def extract_resource_fields(
    reader: SnapshotReader,
    resource_addr: int,
    *,
    gold_offset: int,
    lumber_offset: int,
    food_offset: int | None = None,
    build: str,
    profile: str,
    source: str,
    qualification: str = "confirmed",
    pointer_size: int = 4,
) -> list[LiveFieldEvidence]:
    """Read calibrated f32 fields without rounding or guessing food offsets.

    Fixed-point integer resource layouts should declare ``i32`` fields through
    ``extract_layout_fields`` and preserve their scale in separate provenance.
    """
    offsets = {"gold": gold_offset, "lumber": lumber_offset}
    if food_offset is not None:
        offsets["food"] = food_offset
    fields = [
        _identity_field(
            resource_addr,
            scope="resource",
            build=build,
            profile=profile,
            source=source,
            qualification=_qualification(qualification),
            pointer_size=_pointer_size(pointer_size),
        ),
        *extract_layout_fields(
            reader,
            resource_addr,
            [
                LiveFieldLayout("resource", key, "f32", source, "confirmed", offset)
                for key, offset in offsets.items()
            ],
            scope="resource",
            build=build,
            profile=profile,
            pointer_size=pointer_size,
            qualification=qualification,
        ),
    ]
    if food_offset is None:
        fields.append(
            observed_field(
                key="food",
                label="人口",
                value=None,
                value_type="f32",
                source=source,
                state="unavailable",
                diagnostics=("未提供经过校准的人口字段偏移",),
                scope="resource",
                build=build,
                profile=profile,
            )
        )
    return fields
