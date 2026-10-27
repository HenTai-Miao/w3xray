"""Strict, pure-data validation and offline coverage for live build profiles.

No address in a profile is read here. Integer limits are the encoded PE/version
domains or the selected architecture's address space, never practical quotas.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PROFILE_KEYS = frozenset(
    {
        "schema_version",
        "id",
        "game_version",
        "engine",
        "arch",
        "pointer_size",
        "tier",
        "status",
        "source",
        "fingerprint",
        "checks",
        "game_struct_rva",
        "unit_list_rva",
        "handle_chain",
        "field_layouts",
    }
)
HANDLE_INTEGER_KEYS = (
    "vmctx_global_rva",
    "handle_mgr_global_rva",
    "player_idx_off",
    "pctx_array_off",
    "selmgr_off",
    "sel_entry_off",
    "entry_pair_off",
    "hm_tableA_base_off",
    "hm_tableA_bound_off",
    "hm_tableB_base_off",
    "hm_tableB_bound_off",
    "wrapper_gen_off",
    "wrapper_alive_off",
    "wrapper_obj_off",
    "unit_type_off",
    "unit_inv_off",
    "inv_slots_off",
    "inv_slot_stride",
    "item_type_off",
)
FIELD_TYPES = frozenset(
    {
        "u8",
        "u16",
        "u32",
        "u64",
        "i8",
        "i16",
        "i32",
        "i64",
        "f32",
        "f64",
        "fourcc",
        "pointer",
    }
)
FIELD_SCOPES = frozenset({"unit", "item", "player", "resource", "module"})
FIELD_QUALIFICATIONS = frozenset({"confirmed", "declared-layout-only"})
_UINT16_MAX = (1 << 16) - 1
_UINT32_MAX = (1 << 32) - 1
_VERSION = re.compile(r"[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+")


@dataclass(frozen=True, slots=True)
class LiveFieldLayout:
    """A read-only field recipe; pointer offsets end at the value's bytes.

    For ``pointer_offsets=(a, b, c)``, read a pointer at ``root+a``, then
    another at ``pointer+b``, then the typed value at ``pointer+c``. A single
    offset needs no pointer dereference. The recipe never calls game code.
    """

    scope: str
    key: str
    value_type: str
    source: str
    evidence: str
    offset: int | None = None
    pointer_offsets: tuple[int, ...] = ()
    label: str = ""

    def to_dict(self) -> dict[str, Any]:
        return field_layout_to_dict(self)


def _mapping(value: object, path: str) -> Mapping[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"档案字段 {path} 需要对象, 实得 {type(value).__name__}")
    result: dict[str, object] = {}
    for key, member in value.items():
        if not isinstance(key, str):
            raise ValueError(f"档案字段 {path} 的键需要字符串: {key!r}")
        result[key] = member
    return result


def _known_keys(
    value: Mapping[str, object], allowed: frozenset[str], path: str
) -> None:
    unknown = value.keys() - allowed
    if unknown:
        raise ValueError(f"档案字段 {path} 含未知键: {', '.join(sorted(unknown))}")


def _required(value: Mapping[str, object], key: str, path: str) -> object:
    if key not in value:
        raise ValueError(f"档案字段 {path}.{key} 缺失")
    return value[key]


def strict_integer(value: object, path: str, *, minimum: int, maximum: int) -> int:
    """Reject coercion and diagnose the actual encoded integer domain."""
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError(f"档案字段 {path} 需要整数, 实得 {type(value).__name__}")
    if not minimum <= value <= maximum:
        raise ValueError(f"档案字段 {path} 超出编码范围 [{minimum}, {maximum}]")
    return value


def _text(value: object, path: str, *, nonempty: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"档案字段 {path} 需要字符串, 实得 {type(value).__name__}")
    if nonempty and not value.strip():
        raise ValueError(f"档案字段 {path} 需要非空字符串")
    try:
        value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as error:
        raise ValueError(f"档案字段 {path} 不是有效 UTF-8 文本") from error
    return value


def _choice(value: object, path: str, allowed: frozenset[str]) -> str:
    text = _text(value, path)
    if text not in allowed:
        raise ValueError(f"档案字段 {path} 不支持 {text!r}; 允许 {sorted(allowed)}")
    return text


def architecture_pointer_size(arch: str) -> int:
    """Return the declared architecture's encoded pointer width."""
    if arch == "x86":
        return 4
    if arch == "x64":
        return 8
    raise ValueError(f"档案 arch 不支持 {arch!r}; 允许 x86/x64")


def _version(value: object) -> str:
    version = _text(value, "game_version")
    if _VERSION.fullmatch(version) is None:
        raise ValueError("档案 game_version 需要四段数字版本号 (a.b.c.d)")
    # Compare digit spellings, avoiding Python's unrelated int-string quota.
    upper = str(_UINT16_MAX)
    for index, part in enumerate(version.split(".")):
        digits = part.lstrip("0") or "0"
        if len(digits) > len(upper) or len(digits) == len(upper) and digits > upper:
            raise ValueError(
                f"档案 game_version[{index}] 超出 Windows VERSION WORD 编码范围"
            )
    return version


def parse_field_layouts(
    value: object, *, arch: str = "x86"
) -> tuple[LiveFieldLayout, ...]:
    """Validate complete optional field recipes without importing providers."""
    pointer_size = architecture_pointer_size(arch)
    if not isinstance(value, list):
        raise ValueError("档案字段 field_layouts 需要数组")
    address_max = (1 << (pointer_size * 8)) - 1
    allowed = frozenset(
        {
            "scope",
            "key",
            "type",
            "offset",
            "pointer_offsets",
            "source",
            "evidence",
            "label",
        }
    )
    layouts: list[LiveFieldLayout] = []
    for index, member in enumerate(value):
        path = f"field_layouts[{index}]"
        data = _mapping(member, path)
        _known_keys(data, allowed, path)
        scope = _choice(_required(data, "scope", path), f"{path}.scope", FIELD_SCOPES)
        key = _text(_required(data, "key", path), f"{path}.key", nonempty=True)
        value_type = _choice(_required(data, "type", path), f"{path}.type", FIELD_TYPES)
        source = _text(_required(data, "source", path), f"{path}.source", nonempty=True)
        evidence = _choice(
            _required(data, "evidence", path), f"{path}.evidence", FIELD_QUALIFICATIONS
        )
        label = _text(data.get("label", ""), f"{path}.label")
        if ("offset" in data) == ("pointer_offsets" in data):
            raise ValueError(f"档案字段 {path} 需要 offset 或 pointer_offsets 二选一")
        offset: int | None = None
        chain: tuple[int, ...] = ()
        if "offset" in data:
            offset = strict_integer(
                data["offset"],
                f"{path}.offset",
                minimum=-address_max,
                maximum=address_max,
            )
        else:
            raw_chain = data["pointer_offsets"]
            if not isinstance(raw_chain, list) or not raw_chain:
                raise ValueError(f"档案字段 {path}.pointer_offsets 需要非空整数数组")
            chain = tuple(
                strict_integer(
                    entry,
                    f"{path}.pointer_offsets[{hop}]",
                    minimum=-address_max,
                    maximum=address_max,
                )
                for hop, entry in enumerate(raw_chain)
            )
        layouts.append(
            LiveFieldLayout(
                scope, key, value_type, source, evidence, offset, chain, label
            )
        )
    return tuple(layouts)


def field_layout_to_dict(layout: LiveFieldLayout) -> dict[str, Any]:
    """Serialize the recipe without code paths or callable values."""
    if layout.offset is not None and layout.pointer_offsets:
        raise ValueError(
            "档案字段 field_layouts 不能同时声明 offset 和 pointer_offsets"
        )
    result: dict[str, Any] = {
        "scope": layout.scope,
        "key": layout.key,
        "type": layout.value_type,
        "source": layout.source,
        "evidence": layout.evidence,
    }
    if layout.label:
        result["label"] = layout.label
    if layout.offset is not None:
        result["offset"] = layout.offset
    else:
        result["pointer_offsets"] = list(layout.pointer_offsets)
    return result


def _fingerprint(value: object, arch: str) -> dict[str, int]:
    data = _mapping(value, "fingerprint")
    _known_keys(data, frozenset({"machine", "timestamp", "image_size"}), "fingerprint")
    result = {
        key: strict_integer(
            _required(data, key, "fingerprint"),
            f"fingerprint.{key}",
            minimum=1 if key == "image_size" else 0,
            maximum=_UINT16_MAX if key == "machine" else _UINT32_MAX,
        )
        for key in ("machine", "timestamp", "image_size")
    }
    expected = 0x14C if arch == "x86" else 0x8664
    if result["machine"] != expected:
        raise ValueError(f"档案 fingerprint.machine 与 {arch} 架构不符")
    return result


def _checks(value: object, image_size: int | None) -> list[dict[str, object]]:
    if not isinstance(value, list):
        raise ValueError("档案字段 checks 需要数组")
    checks: list[dict[str, object]] = []
    for index, member in enumerate(value):
        path = f"checks[{index}]"
        data = _mapping(member, path)
        _known_keys(data, frozenset({"rva", "bytes", "label", "domain"}), path)
        rva = strict_integer(
            _required(data, "rva", path), f"{path}.rva", minimum=0, maximum=_UINT32_MAX
        )
        text = _text(_required(data, "bytes", path), f"{path}.bytes")
        try:
            raw = bytes.fromhex(text)
        except ValueError as error:
            raise ValueError(f"档案字段 {path}.bytes 需要完整十六进制字节") from error
        if not raw:
            raise ValueError(f"档案字段 {path}.bytes 不能为空校验")
        if rva + len(raw) > (1 << 32):
            raise ValueError(f"档案字段 {path} 的字节跨出 PE RVA 编码范围")
        if image_size is not None and rva + len(raw) > image_size:
            raise ValueError(f"档案字段 {path} 的字节跨出 fingerprint.image_size")
        checks.append(
            {
                "rva": rva,
                "bytes": raw.hex(),
                "label": _text(data.get("label", ""), f"{path}.label"),
                "domain": _text(
                    data.get("domain", "text"), f"{path}.domain", nonempty=True
                ),
            }
        )
    return checks


def _handle_chain(
    value: object, pointer_size: int, image_size: int | None
) -> dict[str, object]:
    data = _mapping(value, "handle_chain")
    _known_keys(data, frozenset((*HANDLE_INTEGER_KEYS, "source")), "handle_chain")
    address_max = (1 << (pointer_size * 8)) - 1
    result: dict[str, object] = {}
    for key in HANDLE_INTEGER_KEYS:
        rva = key.endswith("_rva")
        minimum = 0 if rva else 1 if key == "inv_slot_stride" else -address_max
        number = strict_integer(
            _required(data, key, "handle_chain"),
            f"handle_chain.{key}",
            minimum=minimum,
            maximum=_UINT32_MAX if rva else address_max,
        )
        if rva and image_size is not None and number + pointer_size > image_size:
            raise ValueError(f"档案字段 handle_chain.{key} 跨出 fingerprint.image_size")
        result[key] = number
    result["source"] = _text(data.get("source", ""), "handle_chain.source")
    return result


def validate_profile_data(value: object) -> dict[str, Any]:
    """Validate every known schema-v1 member, returning fresh normalized data.

    Missing optional fields keep the historical schema-v1 defaults. Explicit
    malformed members never become omitted fields through truthiness checks.
    """
    data = _mapping(value, "profile")
    _known_keys(data, PROFILE_KEYS, "profile")
    schema = strict_integer(
        data.get("schema_version", 1), "schema_version", minimum=0, maximum=_UINT32_MAX
    )
    if schema != 1:
        raise ValueError(f"档案 schema v{schema} 需要新版工具 (本工具支持 v1)")
    arch = _choice(data.get("arch", "x86"), "arch", frozenset({"x86", "x64"}))
    pointer_size = architecture_pointer_size(arch)
    result: dict[str, Any] = {
        "schema_version": schema,
        "game_version": _version(_required(data, "game_version", "profile")),
        "engine": _choice(
            data.get("engine", "classic"), "engine", frozenset({"classic", "reforged"})
        ),
        "arch": arch,
        "tier": _choice(
            data.get("tier", "exact"),
            "tier",
            frozenset({"exact", "rva-table", "template", "reforged-pending"}),
        ),
        "source": _text(data.get("source", "JSON 导入"), "source"),
    }
    for key in ("id", "status"):
        if key in data:
            result[key] = _text(data[key], key, nonempty=True)
    if "pointer_size" in data:
        width = strict_integer(
            data["pointer_size"], "pointer_size", minimum=4, maximum=8
        )
        if width != pointer_size:
            raise ValueError(
                f"档案 pointer_size 必须与 {arch} 的 {pointer_size} 字节指针一致"
            )
        result["pointer_size"] = width
    image_size: int | None = None
    if "fingerprint" in data:
        result["fingerprint"] = (
            None
            if data["fingerprint"] is None
            else _fingerprint(data["fingerprint"], arch)
        )
        if result["fingerprint"] is not None:
            image_size = result["fingerprint"]["image_size"]
    for key in ("game_struct_rva", "unit_list_rva"):
        if key in data:
            number = data[key]
            if number is not None:
                number = strict_integer(number, key, minimum=0, maximum=_UINT32_MAX)
                if image_size is not None and number + pointer_size > image_size:
                    raise ValueError(f"档案字段 {key} 跨出 fingerprint.image_size")
            result[key] = number
    result["checks"] = _checks(data.get("checks", []), image_size)
    if "handle_chain" in data:
        result["handle_chain"] = (
            None
            if data["handle_chain"] is None
            else _handle_chain(data["handle_chain"], pointer_size, image_size)
        )
    result["field_layouts"] = [
        field_layout_to_dict(layout)
        for layout in parse_field_layouts(data.get("field_layouts", []), arch=arch)
    ]
    return result


@dataclass(frozen=True, slots=True)
class ProfileSupport:
    """Offline declaration coverage, explicitly distinct from a live probe."""

    version: str = ""
    engine: str = ""
    arch: str = ""
    tier: str = ""
    source: str = ""
    pointer_size: int | None = None
    fields: tuple[LiveFieldLayout, ...] = ()
    handle_chain_declared: bool = False
    resource_anchor_declared: bool = False
    diagnostics: tuple[str, ...] = ()
    supported: bool = False
    complete: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "game_version": self.version,
            "engine": self.engine,
            "arch": self.arch,
            "tier": self.tier,
            "source": self.source,
            "pointer_size": self.pointer_size,
            "fields": [field_layout_to_dict(layout) for layout in self.fields],
            "handle_chain_declared": self.handle_chain_declared,
            "resource_anchor_declared": self.resource_anchor_declared,
            "diagnostics": list(self.diagnostics),
            "supported": self.supported,
            "complete": self.complete,
            "runtime_verified": False,
        }


def inspect_profile_support(value: object) -> ProfileSupport:
    """Inspect all declared field layouts without reading game memory.

    ``complete`` means the declaration inventory passed schema validation;
    ``supported`` means at least one read recipe/anchor is declared. Neither is
    a statement that an actual process supports those fields.
    """
    try:
        data = validate_profile_data(value)
    except ValueError as error:
        return ProfileSupport(diagnostics=(str(error),))
    fields = list(parse_field_layouts(data["field_layouts"], arch=data["arch"]))
    chain = data.get("handle_chain")
    if chain is not None:
        source = chain["source"] or data["source"]
        for scope, key, value_type, offset_key in (
            ("unit", "code", "fourcc", "unit_type_off"),
            ("unit", "inventory", "pointer", "unit_inv_off"),
            ("item", "code", "fourcc", "item_type_off"),
        ):
            fields.append(
                LiveFieldLayout(
                    scope,
                    key,
                    value_type,
                    source,
                    "declared-layout-only",
                    offset=chain[offset_key],
                )
            )
    has_anchor = data.get("game_struct_rva") is not None
    diagnostics = ["仅检查档案声明；未读取进程，字段语义和当前 build 仍需独立核验。"]
    if data["tier"] != "exact":
        diagnostics.append(f"档案档位 {data['tier']}；未声明已真机验证的完整读取能力。")
    if not fields:
        diagnostics.append("未声明可读取字段；HP/MP/次数等未验证布局保持不可用。")
    return ProfileSupport(
        version=data["game_version"],
        engine=data["engine"],
        arch=data["arch"],
        tier=data["tier"],
        source=data["source"],
        pointer_size=architecture_pointer_size(data["arch"]),
        fields=tuple(fields),
        handle_chain_declared=chain is not None,
        resource_anchor_declared=has_anchor,
        diagnostics=tuple(diagnostics),
        supported=bool(fields) or chain is not None or has_anchor,
        complete=True,
    )
