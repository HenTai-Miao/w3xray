"""Lossless, offline interpretation of explicitly declared equipment plans.

The two schema-1 shapes are data contracts, not evidence of a running game,
ownership, item availability, equipment effects, or a supported restore path.
"""

from __future__ import annotations

import base64
from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import re

from .hotkey_config import parse_hotkey_json
from .hotkey_config_models import JsonNode
from .object_codes import valid_object_code
from .save_text_encoding import inspect_save_text


_UNSIGNED_INTEGER = re.compile(r"(?:-?0|[1-9][0-9]*)\Z")
_RECORD_FIELDS = frozenset(
    {"name", "unit_type_id", "equipment", "equipment_charges", "requires_any_slot"}
)
_NOTICE = (
    "仅解释所选文件声明的离线方案；不证明物品属于玩家、可装备或具有某种效果，"
    "不读取游戏，也不恢复或修改游戏。"
)
_RECOVERY = (
    "可在离线存档工作台查看完整原文和诊断，选择原工具导出的方案 JSON 后重新分析；"
    "物品信息请用对应地图的 item 查询核对。"
)


@dataclass(frozen=True, slots=True)
class LoadoutDiagnostic:
    code: str
    severity: str
    path: str
    message: str
    node: int | None = None


@dataclass(frozen=True, slots=True)
class LoadoutCharge:
    sequence: int
    index: int
    node: int
    literal: str | None
    state: str


@dataclass(frozen=True, slots=True)
class LoadoutSlot:
    """One encoded slot; sequence distinguishes repeated equipment declarations."""

    sequence: int
    index: int
    node: int
    code: str | None
    state: str
    item_node: int | None = None
    type_node: int | None = None
    type_literal: str | None = None
    charge_node: int | None = None
    charge_literal: str | None = None


@dataclass(frozen=True, slots=True)
class LoadoutRecord:
    ordinal: int
    kind: str
    path: str
    node: int
    name: str | None
    unit_code: str | None
    unit_state: str
    requires_any_slot: bool | None
    slots: tuple[LoadoutSlot, ...]
    charges: tuple[LoadoutCharge, ...] = ()
    state: str = "confirmed"


def _unicode_text(value: str) -> str:
    """Keep exported reports encodable; the exact JSON token remains available."""
    return value.encode("utf-8", errors="backslashreplace").decode("utf-8")


@dataclass(frozen=True, slots=True)
class LoadoutDocument:
    source: str
    sha256: str
    size: int
    status: str
    kind: str
    raw_base64: str
    raw_text: str | None
    encoding: str
    bom_bytes: int
    nodes: tuple[JsonNode, ...]
    root: int | None
    byte_spans: tuple[tuple[int, int], ...]
    records: tuple[LoadoutRecord, ...]
    diagnostics: tuple[LoadoutDiagnostic, ...]

    @property
    def recognized(self) -> bool:
        return bool(self.kind)

    @property
    def complete(self) -> bool:
        return self.status == "confirmed"

    def raw_token(self, node: int) -> str:
        if self.raw_text is None:
            raise ValueError("来源没有已确认文本；请查看原始字节或明确文本编码。")
        value = self.nodes[node]
        return self.raw_text[value.start : value.end]

    def to_dict(self) -> dict[str, object]:
        """Flat syntax evidence retains duplicate keys and arbitrarily deep data."""
        syntax = []
        for index, (node, span) in enumerate(
            zip(self.nodes, self.byte_spans, strict=True)
        ):
            syntax.append(
                {
                    "node": index,
                    "kind": node.kind,
                    "offset": node.start,
                    "end": node.end,
                    "byte_offset": span[0],
                    "byte_end": span[1],
                    "value": _unicode_text(node.value)
                    if isinstance(node.value, str)
                    else node.value,
                    "members": [
                        {"key": _unicode_text(member.key), "node": member.node}
                        for member in node.members
                    ],
                    "elements": list(node.elements),
                }
            )
        return {
            "format": "gamexray-offline-loadout-evidence",
            "schema_version": 1,
            "source": self.source,
            "sha256": self.sha256,
            "size": self.size,
            "status": self.status,
            "kind": self.kind,
            "recognized": self.recognized,
            "complete": self.complete,
            "raw_base64": self.raw_base64,
            "raw_text": self.raw_text,
            "encoding": self.encoding,
            "bom_bytes": self.bom_bytes,
            "root": self.root,
            "nodes": syntax,
            "records": [asdict(record) for record in self.records],
            "diagnostics": [asdict(note) for note in self.diagnostics],
            "notice": _NOTICE,
            "recovery": _RECOVERY,
        }


class _PlanReader:
    def __init__(self, nodes: tuple[JsonNode, ...]) -> None:
        self.nodes = nodes
        self.diagnostics: list[LoadoutDiagnostic] = []

    def diagnostic(
        self,
        code: str,
        path: str,
        message: str,
        node: int | None = None,
        severity: str = "error",
    ) -> None:
        self.diagnostics.append(LoadoutDiagnostic(code, severity, path, message, node))

    def declarations(self, node: int, key: str) -> tuple[int, ...]:
        return tuple(
            member.node for member in self.nodes[node].members if member.key == key
        )

    def single(self, node: int, key: str, path: str) -> int | None:
        values = self.declarations(node, key)
        if not values:
            self.diagnostic(
                "missing-field", path, f"缺少声明字段 {key}；没有补默认值。", node
            )
        return values[0] if len(values) == 1 else None

    def all_json_diagnostics(self) -> None:
        for index, node in enumerate(self.nodes):
            if node.kind == "object":
                counts = Counter(member.key for member in node.members)
                for key, count in counts.items():
                    if count > 1:
                        self.diagnostic(
                            "duplicate-json-key",
                            f"node[{index}][{json.dumps(key, ensure_ascii=True)}]",
                            f"字段重复声明 {count} 次；完整保留原顺序与每个值，没有选择最后一项。",
                            index,
                        )
            texts = [member.key for member in node.members]
            if isinstance(node.value, str) and node.kind == "string":
                texts.append(node.value)
            if any(
                any(0xD800 <= ord(char) <= 0xDFFF for char in text) for text in texts
            ):
                self.diagnostic(
                    "unpaired-unicode-surrogate",
                    f"node[{index}]",
                    "JSON 转义包含未配对的 Unicode 代理值；保留原始 token，显示时使用转义文本。",
                    index,
                )

    def extensions(self, node: int, known: frozenset[str], path: str) -> None:
        for member in self.nodes[node].members:
            if member.key not in known:
                self.diagnostic(
                    "extension-field",
                    path + "[" + json.dumps(member.key, ensure_ascii=True) + "]",
                    "未解释的扩展字段已完整保留在原始 JSON 和节点索引中。",
                    member.node,
                    "info",
                )

    def unsigned(self, node: int | None) -> str | None:
        if node is None:
            return None
        value = self.nodes[node]
        if (
            value.kind == "number"
            and isinstance(value.value, str)
            and _UNSIGNED_INTEGER.fullmatch(value.value)
        ):
            return value.value
        return None

    def identity(self, node: int | None, path: str) -> tuple[str | None, str]:
        literal = self.unsigned(node)
        if (
            literal is None
            or len(literal) > 10
            or (len(literal) == 10 and literal > "4294967295")
        ):
            self.diagnostic(
                "invalid-identity",
                path,
                "对象身份需要 uint32 整数声明；完整原值已保留，没有截断、转浮点或猜测四码。",
                node,
            )
            return None, "invalid"
        if literal in {"0", "-0"}:
            return None, "empty"
        return int(literal).to_bytes(4, "big").decode("latin-1"), "confirmed"

    def array(
        self, node: int, path: str, expected: int | None = None
    ) -> tuple[int, ...]:
        value = self.nodes[node]
        if value.kind != "array":
            self.diagnostic(
                "invalid-array", path, "此角色需要数组；原声明完整保留。", node
            )
            return ()
        if expected is not None and len(value.elements) != expected:
            self.diagnostic(
                "slot-count",
                path,
                f"schema 1 对此数组声明 {expected} 项，实际为 {len(value.elements)}；所有项均保留。",
                node,
            )
        return value.elements

    def artifact(
        self, node: int, ordinal: int, path: str, trusted: bool
    ) -> LoadoutRecord:
        before = len(self.diagnostics)
        slots: list[LoadoutSlot] = []
        entries = self.array(node, path, 6)
        for index, child in enumerate(entries, 1):
            value = self.nodes[child]
            code = (
                value.value
                if value.kind == "string" and isinstance(value.value, str)
                else None
            )
            valid = code is not None and valid_object_code(code)
            if not valid:
                self.diagnostic(
                    "invalid-identity",
                    f"{path}[{index - 1}]",
                    "物品代码需要完整四字节 Latin-1 字符串；不去空格、不折叠大小写、不补齐。",
                    child,
                )
            slots.append(
                LoadoutSlot(
                    ordinal,
                    index,
                    child,
                    code if valid else None,
                    "confirmed"
                    if valid and trusted
                    else "unverified"
                    if valid
                    else "invalid",
                    item_node=child,
                )
            )
        clean = not any(note.severity == "error" for note in self.diagnostics[before:])
        return LoadoutRecord(
            ordinal,
            "artifact-plan",
            path,
            node,
            None,
            None,
            "not-declared",
            None,
            tuple(slots),
            state="confirmed" if trusted and clean else "partial",
        )

    def equipment(
        self, node: int, ordinal: int, path: str, trusted: bool
    ) -> LoadoutRecord:
        before = len(self.diagnostics)
        value = self.nodes[node]
        if value.kind != "object":
            self.diagnostic(
                "invalid-record", path, "套装记录需要对象；该项完整保留。", node
            )
            return LoadoutRecord(
                ordinal,
                "equipment-loadouts",
                path,
                node,
                None,
                None,
                "invalid",
                None,
                (),
                state="partial",
            )
        self.extensions(node, _RECORD_FIELDS, path)
        name_node = self.single(node, "name", path)
        name = None if name_node is None else self.nodes[name_node].value
        if (
            name_node is None
            or self.nodes[name_node].kind != "string"
            or not isinstance(name, str)
            or not name.strip()
            or any(0xD800 <= ord(char) <= 0xDFFF for char in name)
        ):
            self.diagnostic(
                "invalid-name",
                path,
                "名称缺失、重复或不是非空文本；未选择默认名称。",
                name_node,
            )
            name = None
        unit_node = self.single(node, "unit_type_id", path)
        unit_code, unit_state = self.identity(unit_node, path + '["unit_type_id"]')
        any_node = self.single(node, "requires_any_slot", path)
        requires_any = None if any_node is None else self.nodes[any_node].value
        if (
            any_node is None
            or self.nodes[any_node].kind != "boolean"
            or not isinstance(requires_any, bool)
        ):
            self.diagnostic(
                "invalid-boolean",
                path,
                "requires_any_slot 需要唯一布尔声明；未推测其值。",
                any_node,
            )
            requires_any = None
        equipment_nodes = self.declarations(node, "equipment")
        charge_nodes = self.declarations(node, "equipment_charges")
        if not equipment_nodes:
            self.single(node, "equipment", path)
        if not charge_nodes:
            self.single(node, "equipment_charges", path)
        charges: list[LoadoutCharge] = []
        charge_sequences: list[tuple[int, ...]] = []
        for sequence, declared in enumerate(charge_nodes, 1):
            children = self.array(declared, path + '["equipment_charges"]', 9)
            charge_sequences.append(children)
            for index, child in enumerate(children, 1):
                literal = self.unsigned(child)
                if literal is None:
                    self.diagnostic(
                        "invalid-quantity",
                        f'{path}["equipment_charges"][{index - 1}]',
                        "数量需要非负整数 token；完整原值保留，没有取整或补零。",
                        child,
                    )
                charges.append(
                    LoadoutCharge(
                        sequence,
                        index,
                        child,
                        literal,
                        "confirmed" if literal is not None else "invalid",
                    )
                )
        unambiguous = len(equipment_nodes) == 1 and len(charge_nodes) == 1
        charge_sequence = charge_sequences[0] if unambiguous else ()
        slots: list[LoadoutSlot] = []
        for sequence, declared in enumerate(equipment_nodes, 1):
            entries = self.array(declared, path + '["equipment"]', 9)
            if unambiguous and len(entries) != len(charge_sequence):
                self.diagnostic(
                    "quantity-count",
                    path,
                    f"物品项 {len(entries)} 个与数量项 {len(charge_sequence)} 个不等长；保留全部项，不补齐或丢弃。",
                    declared,
                )
            for index, child in enumerate(entries, 1):
                slot_path = f'{path}["equipment"][{index - 1}]'
                row = self.array(child, slot_path, 2)
                item_node = row[0] if row else None
                type_node = row[1] if len(row) >= 2 else None
                code, state = self.identity(item_node, slot_path)
                kind = self.unsigned(type_node)
                kind_valid = kind is not None and (len(kind) == 1 or kind == "-0")
                if not kind_valid:
                    self.diagnostic(
                        "invalid-equipment-type",
                        slot_path,
                        "装备类型需要 schema 1 声明的 0 至 9 整数；没有按物品代码猜测类型。",
                        type_node,
                    )
                charge_node = (
                    charge_sequence[index - 1]
                    if index <= len(charge_sequence)
                    else None
                )
                quantity = self.unsigned(charge_node)
                valid = (
                    state != "invalid"
                    and kind_valid
                    and len(row) == 2
                    and quantity is not None
                )
                slots.append(
                    LoadoutSlot(
                        sequence,
                        index,
                        child,
                        code,
                        state
                        if valid and trusted and unambiguous
                        else "unverified"
                        if state != "invalid"
                        else "invalid",
                        item_node,
                        type_node,
                        kind,
                        charge_node,
                        quantity,
                    )
                )
        clean = not any(note.severity == "error" for note in self.diagnostics[before:])
        repeated = any(
            count > 1
            for count in Counter(member.key for member in value.members).values()
        )
        return LoadoutRecord(
            ordinal,
            "equipment-loadouts",
            path,
            node,
            name,
            unit_code,
            unit_state if trusted else "unverified",
            requires_any,
            tuple(slots),
            tuple(charges),
            "confirmed" if trusted and clean and not repeated else "partial",
        )


def _byte_spans(
    text: str, encoding: str, bom_bytes: int, nodes: tuple[JsonNode, ...]
) -> tuple[tuple[int, int], ...]:
    boundaries = sorted({point for node in nodes for point in (node.start, node.end)})
    positions: dict[int, int] = {}
    previous = 0
    byte_position = bom_bytes
    for boundary in boundaries:
        byte_position += len(text[previous:boundary].encode(encoding))
        positions[boundary] = byte_position
        previous = boundary
    return tuple((positions[node.start], positions[node.end]) for node in nodes)


def inspect_loadout_document(
    payload: bytes, source: str = "", *, text_encoding: str = "auto"
) -> LoadoutDocument:
    """Inspect all bytes without file I/O, game access, default caps or mutation."""
    decoded = inspect_save_text(payload, text_encoding)
    text = decoded.text
    nodes: tuple[JsonNode, ...] = ()
    root: int | None = None
    records: list[LoadoutRecord] = []
    reader = _PlanReader(nodes)
    kind = ""
    status = "not-plan"
    if text is None:
        status = "partial"
        for message in decoded.diagnostics:
            reader.diagnostic("text-encoding", "$", message)
    else:
        try:
            nodes, root = parse_hotkey_json(text)
        except ValueError as exc:
            status = "partial"
            reader.diagnostic(
                "json-invalid",
                "$",
                f"JSON 未完整解析，无法确认方案结构：{exc}；原始字节和文本完整保留。",
            )
        else:
            reader = _PlanReader(nodes)
            reader.all_json_diagnostics()
            if nodes[root].kind == "object":
                keys = {member.key for member in nodes[root].members}
                artifacts = "codes" in keys and "schema" in keys
                loadouts = "records" in keys and "schema" in keys
                kind = (
                    "ambiguous"
                    if artifacts and loadouts
                    else "artifact-plan"
                    if artifacts
                    else "equipment-loadouts"
                    if loadouts
                    else ""
                )
                if kind:
                    schema = reader.single(root, "schema", "$")
                    schema_ok = reader.unsigned(schema) == "1"
                    if not schema_ok:
                        reader.diagnostic(
                            "unsupported-schema",
                            "$",
                            "需要唯一整数 schema=1；保留候选声明，不按其他版本猜测可用方案。",
                            schema,
                        )
                    if kind == "ambiguous":
                        reader.diagnostic(
                            "ambiguous-plan-kind",
                            "$",
                            "同时声明 codes 和 records；两组证据分别保留，没有选择一种方案格式。",
                            root,
                        )
                    reader.extensions(
                        root,
                        frozenset({"schema", "codes" if artifacts else "records"})
                        if kind != "ambiguous"
                        else frozenset({"schema", "codes", "records"}),
                        "$",
                    )
                    if artifacts:
                        declarations = reader.declarations(root, "codes")
                        for index, node in enumerate(declarations, 1):
                            records.append(
                                reader.artifact(
                                    node,
                                    index,
                                    '$["codes"]',
                                    schema_ok
                                    and kind != "ambiguous"
                                    and len(declarations) == 1,
                                )
                            )
                    if loadouts:
                        declarations = reader.declarations(root, "records")
                        for declared in declarations:
                            for node in reader.array(declared, '$["records"]'):
                                records.append(
                                    reader.equipment(
                                        node,
                                        len(records) + 1,
                                        f'$["records"][{len(records)}]',
                                        schema_ok
                                        and kind != "ambiguous"
                                        and len(declarations) == 1,
                                    )
                                )
                    status = (
                        "partial"
                        if any(note.severity == "error" for note in reader.diagnostics)
                        else "confirmed"
                    )
            if not kind:
                reader.diagnostic(
                    "not-plan",
                    "$",
                    "没有识别到 schema 与 codes/records 配对的方案声明；可继续查看原始 JSON，或选择原工具导出的六槽/九槽方案。",
                    root,
                    "info",
                )
    return LoadoutDocument(
        source,
        hashlib.sha256(payload).hexdigest(),
        len(payload),
        status,
        kind,
        base64.b64encode(payload).decode("ascii"),
        text,
        decoded.encoding,
        decoded.bom_bytes,
        nodes,
        root,
        _byte_spans(text, decoded.encoding, decoded.bom_bytes, nodes)
        if text is not None and nodes
        else (),
        tuple(records),
        tuple(reader.diagnostics),
    )


__all__ = (
    "LoadoutCharge",
    "LoadoutDiagnostic",
    "LoadoutDocument",
    "LoadoutRecord",
    "LoadoutSlot",
    "inspect_loadout_document",
)
