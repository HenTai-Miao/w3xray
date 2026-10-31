# -*- coding: utf-8 -*-
"""运行中游戏内存的对象文本证据导出 (live --dump-objects)。

部分游戏进程内存含 SLK 派生文本候选:
块头形如 ``\\n\\r\\n[n00M\\x00`` (区域首个块可为 ``\\r\\n[四码\\x00``),
字段形如 ``\\n字段键\\x00值\\x00`` 依次排列 (多级值内层 \\x00 分隔)。

本模块保留每个候选块的地址、原始字节、重复字段和冲突。四码本身不能
证明类别、基础 ID、自定义状态或当前值；未分类证据可用知识包 text 查询。

边界: 全程 ReadProcessMemory 只读; 不注入、不写游戏内存、不解密壳算法——
内存观察不是地图来源完整性证明，也不是游戏线程的原子快照。
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import time

from .batch_tsv import format_tsv_rows
from .json_evidence import JsonNode, parse_json_evidence
from .live_report_io import read_report_bytes, verify_report_source, write_report_bytes
from .live_report_json import format_report_json, parse_report_json
from .object_codes import valid_object_code
from .object_export_coverage import OBJECT_COVERAGE_COLUMN, OBJECT_COVERAGE_FILE
from .pack_query_objects import OBJECT_TABLES

__all__ = (
    "LiveObjectDumpResult",
    "category_of",
    "dump_live_objects",
    "extract_affix_definitions",
    "extract_registered_records",
    "parse_slk_blocks",
    "write_object_pack",
)

# Bound each native allocation, then consume every chunk of each readable region.
_READ_CHUNK_BYTES = 16 * 1024 * 1024

# 身份是四字节 Latin-1；标点、高位字节和空白不改变长度。
_BLOCK_HEADER = re.compile(rb"(?:\n\r\n|\A\r\n)\[([\s\S]{4})\x00")
# 字段: \n<键>\x00<值>\x00 — 值不跨行; 多级值内层 \x00 由值段容纳
_FIELD = re.compile(rb"\n([^\n\x00]+)\x00([^\n]*?)\x00(?=\n|$)")

# ---------------------------------------------------------------------------
# Lua 数据层 (云消息/词缀表) — 模式驱动, 无地图特定词表。
#
# Lua 架构地图把运行时配置 (装备词条/掉落池/商店) 以 JSON 云消息与 Lua
# 常量池驻留内存。两类通用结构可无词表提取:
#   A) JSON 云消息: {"page":..,"info":"{\"name\":\"<消息名>\",\"params\":[..]}"}
#      —— 按「消息名」聚合去重; 消息名本身也是从内存收集的, 不硬编码。
#   B) 词缀/词条定义: 「XX：提供（LV*N）YYY」/「XX：提供（LV*N）的YYY」形态的
#      公式化描述行 —— 倍率与属性名从原文捕获, 不猜。

_JSON_MSG = re.compile(rb'\{\s*"page"\s*:')
_AFFIX_PATTERN = re.compile(
    "([\u4e00-\u9fff]+)：提供\\|cff00ff00（LV\\*([\\d.]+)）\\|r(?:点|的)?([\\u4e00-\\u9fff/%/]*)"
)

_OBJECT_ID_HEADER = (
    "分类",
    "ID",
    "10进制",
    "基础ID",
    "名称",
    "自定义",
    "说明",
    OBJECT_COVERAGE_COLUMN,
)
_FIELD_HEADER = (
    "分类",
    "ID",
    "名称",
    "字段键",
    "字段名",
    "值",
    "来源",
    OBJECT_COVERAGE_COLUMN,
)
_RUNTIME_BOUNDARY = (
    "运行时只读文本观察；未证明地图/归档来源、对象类别、基础 ID、自定义状态或当前值。"
    "可读内存扫描不等于原地图完整覆盖，也不是原子快照；全部对象类别保持 partial。"
    "未分类文本请用 pack-query text 查询；原始块、重复来源和冲突均保留。"
)


@dataclass(frozen=True, slots=True)
class SlkFieldEvidence:
    address: int
    raw: bytes
    key_raw: bytes
    value_raw: bytes
    key: str | None
    value: str | None
    diagnostics: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class SlkBlockEvidence:
    code: str
    address: int
    raw: bytes
    region_address: int
    region_size: int
    region_sha256: str
    fields: tuple[SlkFieldEvidence, ...]
    diagnostics: tuple[str, ...] = ()


class SlkBlocks(dict[str, dict[str, str]]):
    """Compatible unambiguous text view beside complete independent evidence."""

    def __init__(
        self,
        values: dict[str, dict[str, str]],
        records: tuple[SlkBlockEvidence, ...],
        diagnostics: tuple[str, ...],
    ) -> None:
        super().__init__(values)
        self.records = records
        self.diagnostics = diagnostics


@dataclass(frozen=True, slots=True)
class RuntimeTextEvidence:
    address: int
    raw: bytes
    name: str = ""
    values: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()


class RegisteredRecords(dict[str, dict[str, list[object]]]):
    evidence: tuple[RuntimeTextEvidence, ...] = ()


class AffixDefinitions(dict[str, dict[str, str]]):
    evidence: tuple[RuntimeTextEvidence, ...] = ()


class CapturedRegions(list[tuple[int, bytes]]):
    def __init__(self) -> None:
        super().__init__()
        self.diagnostics: list[str] = []


def _json_member(nodes: tuple[JsonNode, ...], root: int, key: str) -> JsonNode:
    if nodes[root].kind != "object":
        raise ValueError("JSON 消息必须是 object")
    members = [member for member in nodes[root].members if member.key == key]
    if len(members) != 1:
        raise ValueError(f"JSON 字段 {key!r} 缺失或重复；未选择值")
    return nodes[members[0].node]


@dataclass(frozen=True, slots=True)
class LiveObjectDumpResult:
    """一次内存对象表导出的结果摘要。"""

    pid: int
    regions: int
    scanned_mb: int
    objects: int
    duplicates: int
    categories: dict[str, int]
    out_dir: str
    files: int
    notes: tuple[str, ...] = ()
    completed: bool = False
    records: int = 0
    registered_records: int = 0
    affix_records: int = 0


def category_of(code: str) -> str:
    """An observed four-byte identity has no category evidence by itself."""
    if not valid_object_code(code):
        raise ValueError(f"对象 ID 不是完整四字节 Latin-1 身份: {code!r}")
    return "未分类"


def parse_slk_blocks(
    regions: list[tuple[int, bytes]],
) -> tuple[SlkBlocks, int]:
    """保留所有候选块；字典视图仅含各来源无冲突的完整 UTF-8 字段。

    相邻捕获片段合并，缺失字节绝不补齐。重复计数只表示四码重复出现，
    不证明来自同一张表；冲突、截断和不可解码字节均有独立原始证据。
    """
    blocks: dict[str, dict[str, str]] = {}
    values: dict[str, dict[str, set[str | None]]] = {}
    records: list[SlkBlockEvidence] = []
    diagnostics: list[str] = []
    duplicates = 0
    from .memory_regions import contiguous_regions

    for base, data in contiguous_regions(regions):
        starts = list(_BLOCK_HEADER.finditer(data))
        if not starts:
            continue
        region_sha256 = hashlib.sha256(data).hexdigest()
        for index, match in enumerate(starts):
            code = match.group(1).decode("latin-1")
            end = starts[index + 1].start() if index + 1 < len(starts) else len(data)
            if code in blocks:
                duplicates += 1
            fields, field_notes = _parse_field_evidence(
                data[match.end() : end], base + match.end()
            )
            records.append(
                SlkBlockEvidence(
                    code,
                    base + match.start(),
                    data[match.start() : end],
                    base,
                    len(data),
                    region_sha256,
                    fields,
                    field_notes,
                )
            )
            diagnostics.extend(field_notes)
            blocks.setdefault(code, {})
            observed = values.setdefault(code, {})
            for field in fields:
                if field.key is not None:
                    observed.setdefault(field.key, set()).add(field.value)
    for code, observed in values.items():
        for key, choices in observed.items():
            if len(choices) == 1 and None not in choices:
                value = next(iter(choices))
                assert value is not None
                blocks[code][key] = value
            else:
                diagnostics.append(
                    f"{code!r} 字段 {key!r} 的来源值冲突或不能完整解码；"
                    "未选择当前值，全部原始字段见 未分类对象字段.tsv。"
                )
    return SlkBlocks(blocks, tuple(records), tuple(diagnostics)), duplicates


def _parse_field_evidence(
    body: bytes, address: int
) -> tuple[tuple[SlkFieldEvidence, ...], tuple[str, ...]]:
    fields: list[SlkFieldEvidence] = []
    notes: list[str] = []
    cursor = 0
    for match in _FIELD.finditer(body):
        if body[cursor : match.start()].strip(b"\r\n"):
            notes.append(
                f"0x{address + cursor:X}..0x{address + match.start():X}: "
                "未识别字段字节；原始块完整保留。"
            )
        messages: list[str] = []
        decoded: list[str | None] = []
        for part, label in ((match.group(1), "字段键"), (match.group(2), "字段值")):
            try:
                decoded.append(part.decode("utf-8"))
            except UnicodeDecodeError as exc:
                decoded.append(None)
                messages.append(f"0x{address + match.start():X} {label}: {exc}")
        fields.append(
            SlkFieldEvidence(
                address + match.start(),
                match.group(),
                match.group(1),
                match.group(2),
                decoded[0],
                decoded[1],
                tuple(messages),
            )
        )
        notes.extend(messages)
        cursor = match.end()
    if body[cursor:].strip(b"\r\n"):
        notes.append(
            f"0x{address + cursor:X}..0x{address + len(body):X}: "
            "末尾字段不完整或无法识别；原始块完整保留。"
        )
    return tuple(fields), tuple(notes)


def extract_registered_records(
    regions: list[tuple[int, bytes]],
) -> RegisteredRecords:
    """收集云消息；兼容视图去重，原始记录保留所有来源、数字和重复键。

    Lua 架构地图用 ``{"page":..,"info":"{\"name\":\"<名>\",\"params\":[..]}"}``
    云消息同步运行时配置 (如装备词条注册)。同一消息会因多拷贝/重发重复;
    消息名不做硬编码。非 object/不完整/角色冲突的消息保留诊断，
    不会因为单条消息而中断全量收集，也不把 replacement 解码当作原文。
    """
    by_name = RegisteredRecords()
    evidence: list[RuntimeTextEvidence] = []
    seen_params: dict[str, set[str]] = {}
    from .memory_regions import contiguous_regions

    for base, data in contiguous_regions(regions):
        for match in _JSON_MSG.finditer(data):
            end = data.find(b"\x00", match.start())
            raw = data[match.start() : end if end >= 0 else len(data)]
            name = ""
            params_text = ""
            try:
                nodes, root = parse_json_evidence(raw.decode("utf-8"))
                info = _json_member(nodes, root, "info")
                if info.kind != "string" or not isinstance(info.value, str):
                    raise ValueError("JSON info 必须是嵌套 JSON 字符串")
                inner, inner_root = parse_json_evidence(info.value)
                declared_name = _json_member(inner, inner_root, "name")
                if (
                    declared_name.kind != "string"
                    or not isinstance(declared_name.value, str)
                    or not declared_name.value
                ):
                    raise ValueError("JSON name 必须是非空字符串")
                declared_name.value.encode("utf-8")
                name = declared_name.value
                param_node = _json_member(inner, inner_root, "params")
                if param_node.kind != "array":
                    raise ValueError("JSON params 必须是数组")
                candidate_params = info.value[param_node.start : param_node.end]
                candidate_params.encode("utf-8")
                params_text = candidate_params
                params = parse_report_json(params_text)
                if not isinstance(params, list):
                    raise ValueError("JSON params 必须是数组")
            except (ValueError, UnicodeError) as exc:
                evidence.append(
                    RuntimeTextEvidence(
                        base + match.start(),
                        raw,
                        name,
                        (params_text,) if params_text else (),
                        (str(exc),),
                    )
                )
                continue
            evidence.append(
                RuntimeTextEvidence(
                    base + match.start(),
                    raw,
                    name,
                    (params_text,),
                )
            )
            bucket = by_name.setdefault(name, {"records": []})
            # 每条记录的完整 params 列表; 同名不同 params 都保留 (不同实例)
            key = params_text
            keys = seen_params.setdefault(name, set())
            if key in keys:
                continue
            keys.add(key)
            records = bucket["records"]
            assert isinstance(records, list)
            records.append(params)
    by_name.evidence = tuple(evidence)
    return by_name


def extract_affix_definitions(
    regions: list[tuple[int, bytes]],
) -> AffixDefinitions:
    """收集「词缀名：提供（LV*倍率）属性」公式定义 (无词表, 模式匹配)。

    Lua 架构地图的装备词条系统在内存常量池里带公式化说明文本。
    UTF-8 词名必须按字符对齐匹配, bytes 正则的字节计数会跨字错位——
    因此先按 \x00 切片、整体尝试 utf-8 解码后再用 str 模式匹配。
    所有独立来源与同名冲突都保留；兼容字典仅返回无冲突的定义。
    """
    defs = AffixDefinitions()
    evidence: list[RuntimeTextEvidence] = []
    choices: dict[str, set[tuple[str, str]]] = {}
    # 直接在 bytes 上找「词名前边界」: 词名以 UTF-8 汉字三字节组开头。
    # 用 (?:^|[^\x80-\xbf]) 锚定三字节组首, 避免逐字节 probe 的 O(n²)。
    lead = re.compile(
        rb"(?:\A|[^\x80-\xbf])(([\xe4-\xe9][\x80-\xbf]{2})+)" + "：提供".encode("utf-8")
    )
    from .memory_regions import contiguous_regions

    for base, data in contiguous_regions(regions):
        for match in lead.finditer(data):
            name_bytes = match.group(1)
            tail_start = match.end()
            tail_end = data.find(b"\x00", tail_start)
            tail = data[tail_start : tail_end if tail_end >= 0 else len(data)]
            try:
                tail_text = tail.decode("utf-8")
            except UnicodeDecodeError:
                continue
            m2 = re.search(
                "\\|cff00ff00（LV\\*([\\d.]+)）\\|r(?:点|的)?([\\u4e00-\\u9fff/%/]*)",
                tail_text,
            )
            if not m2:
                continue
            try:
                name = name_bytes.decode("utf-8")
            except UnicodeDecodeError:
                continue
            values = m2.group(1), m2.group(2)
            choices.setdefault(name, set()).add(values)
            evidence.append(
                RuntimeTextEvidence(
                    base + match.start(1),
                    data[match.start(1) : tail_start]
                    + tail[: len(tail_text[: m2.end()].encode("utf-8"))],
                    name,
                    values,
                )
            )
    for name, values in choices.items():
        if len(values) == 1:
            multiplier, stat_name = next(iter(values))
            defs[name] = {"multiplier": multiplier, "stat": stat_name}
    defs.evidence = tuple(
        RuntimeTextEvidence(
            record.address,
            record.raw,
            record.name,
            record.values,
            ("同名词缀存在不同原文定义；未选择当前值。",)
            if len(choices[record.name]) > 1
            else (),
        )
        for record in evidence
    )
    return defs


def _description(fields: dict[str, str]) -> str:
    """说明列: Ubertip(提示) > Description(描述) > Tip(建造/雇佣提示)。"""
    for key in ("Ubertip", "Description", "Tip"):
        value = fields.get(key, "")
        if value:
            return value
    return ""


def write_object_pack(
    blocks: dict[str, dict[str, str]],
    out_dir: str,
    *,
    provenance: dict[str, object] | None = None,
    registered: dict[str, dict[str, list[object]]] | None = None,
    affixes: dict[str, dict[str, str]] | None = None,
) -> int:
    """独占发布新的证据包；未知类别不会成为已确认的物品/单位。

    所有选中对象类别都声明 partial，空表不能证明原地图类别为空。
    原始块和全部字段是独立根 TSV，保留逻辑记录和可逆安全封套。
    已有非空目录拒绝复用，全部文件验证后才写完成清单。
    """
    records = _block_records(blocks)
    diagnostics = (
        list(blocks.diagnostics)
        if isinstance(blocks, SlkBlocks)
        else ["调用方提供结构化字段，未提供原始内存块/地址；未补造来源字节。"]
    )
    for data in (registered, affixes):
        if isinstance(data, (RegisteredRecords, AffixDefinitions)):
            diagnostics.extend(
                f"0x{record.address:X}: {note}"
                for record in data.evidence
                for note in record.diagnostics
            )
    notes = dict(provenance or {})
    source_notes = notes.get("诊断")
    if isinstance(source_notes, (list, tuple)):
        diagnostics.extend(str(note) for note in source_notes)
    # A caller label cannot override the producer's evidence boundary.
    notes["证据边界"] = _RUNTIME_BOUNDARY
    notes["解析诊断"] = diagnostics
    notes["保留对象块"] = len(records)
    payloads = {
        "对象来源.txt": (
            "\n".join(f"{key}: {value}" for key, value in notes.items()) + "\n"
        ).encode("utf-8"),
        "对象来源.json": json.dumps(notes, ensure_ascii=True, indent=2).encode("utf-8"),
        OBJECT_COVERAGE_FILE: format_tsv_rows(
            [
                ("记录类型", "分类", "选择状态", "完整性", "来源", "诊断"),
                *(
                    ("coverage", category, "selected", "partial", "运行时文本观察", "")
                    for category in OBJECT_TABLES
                ),
                ("diagnostic", "", "", "", "运行时文本观察", _RUNTIME_BOUNDARY),
                *(
                    ("diagnostic", "", "", "", "运行时文本观察", note)
                    for note in diagnostics
                ),
            ]
        ).encode("utf-8"),
        **{
            f"对象ID/{category}.tsv": format_tsv_rows([_OBJECT_ID_HEADER]).encode(
                "utf-8"
            )
            for category in OBJECT_TABLES
        },
        "对象字段.tsv": format_tsv_rows([_FIELD_HEADER]).encode("utf-8"),
    }
    object_rows: list[tuple[str, ...]] = [
        (*_OBJECT_ID_HEADER, "块序号", "来源", "诊断")
    ]
    field_rows: list[tuple[str, ...]] = [
        (
            *_FIELD_HEADER,
            "块序号",
            "字段序号",
            "地址",
            "原始键HEX",
            "原始值HEX",
            "原始字段HEX",
            "诊断",
        )
    ]
    raw_rows = [
        (
            "ID",
            "块序号",
            "地址",
            "字节数",
            "SHA256",
            "原始块HEX",
            "捕获连续区地址",
            "捕获连续区字节数",
            "捕获连续区SHA256",
            "诊断",
        )
    ]
    for ordinal, record in enumerate(records, 1):
        code = record.code
        category = category_of(code)
        fields = _unambiguous_fields(record.fields)
        name = fields.get("Name") or fields.get("Tip") or code
        captured = bool(record.region_sha256)
        source = (
            f"内存文本候选@0x{record.address:X}"
            if captured
            else "调用方结构化字段（无内存来源证明）"
        )
        object_rows.append(
            (
                category,
                code,
                str(int.from_bytes(code.encode("latin-1"), "big")),
                "",
                name,
                "",
                _description(fields),
                OBJECT_COVERAGE_FILE,
                str(ordinal),
                source,
                "；".join(record.diagnostics),
            )
        )
        for field_index, field in enumerate(record.fields, 1):
            field_rows.append(
                (
                    category,
                    code,
                    name,
                    field.key or "",
                    field.key or "",
                    field.value if field.value is not None else "",
                    source,
                    OBJECT_COVERAGE_FILE,
                    str(ordinal),
                    str(field_index),
                    f"0x{field.address:X}" if captured else "",
                    field.key_raw.hex(),
                    field.value_raw.hex(),
                    field.raw.hex(),
                    "；".join(field.diagnostics),
                )
            )
        raw_rows.append(
            (
                code,
                str(ordinal),
                f"0x{record.address:X}" if captured else "",
                str(len(record.raw)) if captured else "",
                hashlib.sha256(record.raw).hexdigest() if captured else "",
                record.raw.hex(),
                f"0x{record.region_address:X}" if captured else "",
                str(record.region_size) if captured else "",
                record.region_sha256,
                "；".join(record.diagnostics),
            )
        )
    payloads.update(
        {
            "未分类对象.tsv": format_tsv_rows(object_rows).encode("utf-8"),
            "未分类对象字段.tsv": format_tsv_rows(field_rows).encode("utf-8"),
            "内存对象原始块.tsv": format_tsv_rows(raw_rows).encode("utf-8"),
        }
    )
    if registered is not None:
        payloads.update(_registered_payloads(registered))
    if affixes is not None:
        payloads.update(_affix_payloads(affixes))
    return _publish_pack(payloads, out_dir)


def _unambiguous_fields(fields: tuple[SlkFieldEvidence, ...]) -> dict[str, str]:
    choices: dict[str, set[str | None]] = {}
    for field in fields:
        if field.key is not None:
            choices.setdefault(field.key, set()).add(field.value)
    return {
        key: next(value for value in values if value is not None)
        for key, values in choices.items()
        if len(values) == 1 and None not in values
    }


def _block_records(blocks: dict[str, dict[str, str]]) -> tuple[SlkBlockEvidence, ...]:
    if isinstance(blocks, SlkBlocks):
        return blocks.records
    records: list[SlkBlockEvidence] = []
    for code, values in blocks.items():
        category_of(code)
        records.append(
            SlkBlockEvidence(
                code,
                0,
                b"",
                0,
                0,
                "",
                tuple(
                    SlkFieldEvidence(
                        0, b"", key.encode("utf-8"), value.encode("utf-8"), key, value
                    )
                    for key, value in values.items()
                ),
                ("结构化输入无原始内存来源证明。",),
            )
        )
    return tuple(records)


def _publish_pack(payloads: dict[str, bytes], out_dir: str) -> int:
    # Reuse the shared report parent's held directory handles and exclusive
    # complete-file publication, including its owned-only failure cleanup.
    from .live_report_io import _parents, validate_report_destination
    from .windows_output_paths import (
        logical_output_path,
        native_output_path,
        validate_output_root,
    )

    validate_output_root(out_dir)
    root = Path(os.path.abspath(logical_output_path(out_dir)))
    for directory in (*reversed(root.parents), root):
        if not os.path.lexists(native_output_path(str(directory))):
            with _parents(directory):
                Path(native_output_path(str(directory))).mkdir()
    with _parents(root / "对象导出清单.json"):
        if any(Path(native_output_path(str(root))).iterdir()):
            raise ValueError(
                f"导出目录已有内容；请使用新的空目录，未覆盖既有资产: {root}"
            )
        id_dir = root / "对象ID"
        Path(native_output_path(str(id_dir))).mkdir()
        with _parents(id_dir / "对象.tsv"):
            for relative in payloads:
                validate_report_destination(root / relative)
            for relative, payload in payloads.items():
                write_report_bytes(root / relative, payload)
            manifest: list[dict[str, object]] = []
            observations = []
            for relative, expected in payloads.items():
                actual, metadata = read_report_bytes(root / relative)
                if actual != expected:
                    raise OSError(
                        f"导出字节在交付前变化，未确认完成: {root / relative}"
                    )
                manifest.append({"relative_path": relative, **metadata})
                observations.append(metadata)

            def verify_payloads() -> None:
                for observation in observations:
                    verify_report_source(observation)

            write_report_bytes(
                root / "对象导出清单.json",
                json.dumps(
                    {
                        "completed": True,
                        "scope": "captured-runtime-text-only",
                        "map_coverage_complete": False,
                        "files": manifest,
                    },
                    ensure_ascii=True,
                    indent=2,
                ).encode("utf-8"),
                verify_source=verify_payloads,
            )
    return len(payloads) + 1


def _region_action(state: int, protect: int, rs: int) -> str:
    """Read every committed readable region, excluding guard pages."""
    if (
        state == 0x1000
        and not protect & 0x100
        and protect & 0xFF in (2, 4, 8, 0x20, 0x40, 0x80)
    ):
        return "read"
    return "ignore"


def _skipped_regions_note(skipped: int) -> str:
    """跳过区域披露文案 — 0 计数也要显式写"无", 禁止静默省略字段。"""
    if skipped <= 0:
        return "无"
    return f"{skipped} 个内存片段未完整读取 (进程变化或页面不可读)"


def _snapshot_regions(
    handle: int, max_addr: int
) -> tuple[list[tuple[int, bytes]], int, int]:
    """VirtualQueryEx + ReadProcessMemory 全量区域读取。

    可读区域全部分块读取；短读/不可读片段计数返回，调用方披露缺口。
    """
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _MBI(ctypes.Structure):
        _fields_ = [
            ("Base", ctypes.c_void_p),
            ("AllocationBase", ctypes.c_void_p),
            ("AllocationProtect", wt.DWORD),
            ("RegionSize", ctypes.c_size_t),
            ("State", wt.DWORD),
            ("Protect", wt.DWORD),
            ("Type", wt.DWORD),
        ]

    query = k32.VirtualQueryEx
    query.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(_MBI), ctypes.c_size_t]
    query.restype = ctypes.c_size_t
    read = k32.ReadProcessMemory
    read.argtypes = [
        wt.HANDLE,
        ctypes.c_void_p,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    read.restype = wt.BOOL
    regions = CapturedRegions()
    total = 0
    skipped = 0
    addr = 0x10000
    mbi = _MBI()
    while addr < max_addr:
        size = query(
            handle, ctypes.c_void_p(addr), ctypes.byref(mbi), ctypes.sizeof(mbi)
        )
        if size != ctypes.sizeof(mbi):
            skipped += 1
            regions.diagnostics.append(
                f"VirtualQueryEx@0x{addr:X} 返回 {size}/{ctypes.sizeof(mbi)} 字节 "
                f"(WinError={ctypes.get_last_error()})；后续至 0x{max_addr:X} 未完成扫描。"
            )
            break
        rs = mbi.RegionSize
        base = mbi.Base or 0
        following = base + rs
        if base > addr or following <= addr:
            skipped += 1
            regions.diagnostics.append(
                f"VirtualQueryEx@0x{addr:X} 返回不连续/不前进区域 "
                f"base=0x{base:X}, size={rs}；后续未完成扫描。"
            )
            break
        action = _region_action(mbi.State or 0, mbi.Protect or 0, rs)
        if action == "read":
            end = min(following, max_addr)
            for start in range(addr, end, _READ_CHUNK_BYTES):
                requested = min(_READ_CHUNK_BYTES, end - start)
                buf = ctypes.create_string_buffer(requested)
                got = ctypes.c_size_t()
                succeeded = read(
                    handle,
                    ctypes.c_void_p(start),
                    buf,
                    requested,
                    ctypes.byref(got),
                )
                if 0 < got.value <= requested:
                    regions.append((start, buf.raw[: got.value]))
                    total += got.value
                if not succeeded or got.value != requested:
                    skipped += 1
                    regions.diagnostics.append(
                        f"ReadProcessMemory@0x{start:X}: {got.value}/{requested} 字节, "
                        f"success={bool(succeeded)}, WinError={ctypes.get_last_error()}；"
                        "仅保留实际读取字节，未填补缺口。"
                    )
        addr = following
    return regions, total, skipped


def _write_registered_data_tsv(
    by_name: dict[str, dict[str, list[object]]], out_dir: str
) -> int:
    """云消息注册数据 → 注册数据.tsv (消息名, 序号, 记录JSON)。

    记录以完整 JSON 列形式落盘 (无损); 消费方按需解析字段。
    """
    payloads = _registered_payloads(by_name)
    for name, payload in payloads.items():
        write_report_bytes(Path(out_dir) / name, payload)
    return len(payloads)


def _registered_payloads(
    by_name: dict[str, dict[str, list[object]]],
) -> dict[str, bytes]:
    rows: list[tuple[str, ...]] = [("消息名", "序号", "记录JSON")]
    payloads: dict[str, bytes] = {}
    if isinstance(by_name, RegisteredRecords):
        evidence_rows = [("地址", "消息名", "记录JSON", "原始消息HEX", "诊断")]
        rows = [("消息名", "序号", "记录JSON", "地址", "诊断")]
        for index, record in enumerate(by_name.evidence):
            params = record.values[0] if record.values else ""
            diagnostics = "；".join(record.diagnostics)
            evidence_rows.append(
                (
                    f"0x{record.address:X}",
                    record.name,
                    params,
                    record.raw.hex(),
                    diagnostics,
                )
            )
            if record.name and record.values:
                rows.append(
                    (
                        record.name,
                        str(index),
                        params,
                        f"0x{record.address:X}",
                        diagnostics,
                    )
                )
        if by_name.evidence:
            payloads["注册消息原始证据.tsv"] = format_tsv_rows(evidence_rows).encode(
                "utf-8"
            )
    else:
        for name in sorted(by_name):
            for index, params in enumerate(by_name[name]["records"]):
                rows.append((name, str(index), format_report_json(params)))
    if len(rows) > 1:
        payloads["注册数据.tsv"] = format_tsv_rows(rows).encode("utf-8")
    return payloads


def _write_affixes_tsv(defs: dict[str, dict[str, str]], out_dir: str) -> int:
    """词缀公式定义 → 词缀表.tsv (词缀名, 倍率, 属性)。"""
    payloads = _affix_payloads(defs)
    for name, payload in payloads.items():
        write_report_bytes(Path(out_dir) / name, payload)
    return len(payloads)


def _affix_payloads(defs: dict[str, dict[str, str]]) -> dict[str, bytes]:
    rows: list[tuple[str, ...]] = [("词缀名", "倍率", "属性")]
    if isinstance(defs, AffixDefinitions):
        rows = [("词缀名", "倍率", "属性", "地址", "原始文本HEX", "诊断")]
        rows.extend(
            (
                record.name,
                *record.values,
                f"0x{record.address:X}",
                record.raw.hex(),
                "；".join(record.diagnostics),
            )
            for record in defs.evidence
        )
    else:
        rows.extend(
            (name, defs[name]["multiplier"], defs[name]["stat"])
            for name in sorted(defs)
        )
    return (
        {"词缀表.tsv": format_tsv_rows(rows).encode("utf-8")} if len(rows) > 1 else {}
    )


def _close_process_handle(handle: int) -> None:
    close = ctypes.WinDLL("kernel32", use_last_error=True).CloseHandle
    close.argtypes = [wt.HANDLE]
    close.restype = wt.BOOL
    close(handle)


def _fail_with_notes(
    notes: tuple[str, ...], out_dir: str, pid: int = 0
) -> "LiveObjectDumpResult":
    """失败出口统一把原因打到 stdout (旧行为静默 exit 2, 用户不知道为什么)。"""
    for note in notes:
        print(f"导出未执行: {note}")
    return LiveObjectDumpResult(pid, 0, 0, 0, 0, {}, out_dir, 0, notes)


def dump_live_objects(
    out_dir: str,
    pid: int | None = None,
    verbose: bool = True,
) -> LiveObjectDumpResult:
    """对运行中的 war3 做只读内存观察并导出全部捕获证据。

    completed 只证明文件交付完成，不证明原地图对象来源完整。
    进程缺失/打开失败时 notes 说明原因，completed=False 且不写文件。
    """
    from .live_inventory import (
        detect_version,
        find_war3_pids,
        mem_setup,
        open_process,
        process_scan_limit,
    )

    notes: list[str] = [_RUNTIME_BOUNDARY]
    mem_setup()
    try:
        pids = find_war3_pids()
    except OSError as exc:
        return _fail_with_notes((str(exc),), out_dir)
    if not pids:
        return _fail_with_notes(("war3 未运行",), out_dir)
    if pid is not None:
        if pid not in pids:
            return _fail_with_notes(
                (f"--pid {pid} 不在运行中的 war3 进程列表 {pids}",), out_dir
            )
        chosen = pid
    elif len(pids) > 1:
        return _fail_with_notes(
            (f"检测到多个 war3 进程 {pids} — 不猜, 用 --pid <PID> 显式选择",),
            out_dir,
        )
    else:
        chosen = pids[0]

    handle = open_process(chosen)
    if not handle:
        return _fail_with_notes(
            (f"OpenProcess 失败 (WinError={ctypes.get_last_error()})；未读取游戏内存",),
            out_dir,
            pid=chosen,
        )
    try:
        version = detect_version(handle)
        version_diagnostics = version.get("diagnostics")
        if isinstance(version_diagnostics, list):
            notes.extend(str(message) for message in version_diagnostics)
        max_addr = process_scan_limit(version)
        regions, total, skipped = _snapshot_regions(handle, max_addr)
    finally:
        _close_process_handle(handle)

    blocks, duplicates = parse_slk_blocks(regions)
    notes.extend(blocks.diagnostics)
    if isinstance(regions, CapturedRegions):
        notes.extend(regions.diagnostics)
    categories: dict[str, int] = {}
    for code in blocks:
        cat = category_of(code)
        categories[cat] = categories.get(cat, 0) + 1
    # Lua 数据层 (云消息注册数据 + 词缀公式) — 无词表, 收到什么导什么
    registered = extract_registered_records(regions)
    affixes = extract_affix_definitions(regions)
    registered_count = sum(
        bool(record.name and record.values) for record in registered.evidence
    )
    affix_count = len(affixes.evidence)
    for data in (registered, affixes):
        notes.extend(
            f"0x{record.address:X}: {note}"
            for record in data.evidence
            for note in record.diagnostics
        )
    skipped_note = _skipped_regions_note(skipped)
    notes_line = f"内存读取缺口: {skipped_note}"
    if skipped:
        notes.append(notes_line)
    if not blocks and not registered_count and not affix_count:
        notes.append(
            "未捕获可识别的对象文本/注册消息/词缀记录；空结果不能证明地图内容不存在。"
        )
    files = write_object_pack(
        blocks,
        out_dir,
        provenance={
            "来源": "live --dump-objects (运行中游戏内存文本候选, 只读)",
            "pid": chosen,
            "版本观察": version,
            "捕获区域身份": [
                {
                    "address": base,
                    "size": len(data),
                    "sha256": hashlib.sha256(data).hexdigest(),
                }
                for base, data in regions
            ],
            "导出时间": time.strftime("%Y-%m-%d %H:%M:%S"),
            "扫描区域": f"{len(regions)} 区 / {total // 1048576}MB",
            "内存读取缺口": skipped_note,
            "四码身份数": len(blocks),
            "重复四码块（均保留）": duplicates,
            "分类": json.dumps(categories, ensure_ascii=False),
            "诊断": notes,
        },
        registered=registered,
        affixes=affixes,
    )
    if verbose:
        print(
            f"内存文本证据导出: {len(blocks)} 个四码身份 / {len(blocks.records)} 个块 "
            f"({len(regions)} 区 {total // 1048576}MB, 重复四码块保留 {duplicates})"
        )
        for note in notes:
            print(f"  {note}")
        for cat, count in sorted(categories.items()):
            print(f"  {cat}: {count}")
        if registered_count:
            print(f"注册消息来源记录: {registered_count} 条")
        if affix_count:
            print(f"词缀原文来源记录: {affix_count} 条")
        print(f"证据包已交付 -> {out_dir} ({files} 个文件)")
        print(
            f'查询示例: uv run python -X utf8 main.py pack-query "{out_dir}" text <名称或四码>'
        )
    return LiveObjectDumpResult(
        chosen,
        len(regions),
        total // 1048576,
        len(blocks),
        duplicates,
        categories,
        out_dir,
        files,
        tuple(notes),
        True,
        len(blocks.records),
        registered_count,
        affix_count,
    )
