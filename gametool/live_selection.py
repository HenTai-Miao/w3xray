"""Read the proved native local selection container, never a unit vtable."""

from __future__ import annotations

import struct
from collections.abc import Callable
from dataclasses import asdict, dataclass
from typing import Generic, Protocol, TypeVar


class SelectionReader(Protocol):
    def read(self, addr: int, size: int) -> bytes | None: ...


class SelectionResolver(Protocol):
    def resolve_evidence(
        self, lo: int, hi: int
    ) -> tuple[int | None, dict[str, int], tuple[str, ...]]: ...


class SelectionInventory(Protocol):
    @property
    def code(self) -> str: ...

    @property
    def diagnostics(self) -> tuple[str, ...]: ...


class SelectionOffsets(Protocol):
    @property
    def vmctx_global_rva(self) -> int: ...

    @property
    def player_idx_off(self) -> int: ...

    @property
    def pctx_array_off(self) -> int: ...

    @property
    def selmgr_off(self) -> int: ...

    @property
    def sel_entry_off(self) -> int: ...

    @property
    def entry_pair_off(self) -> int: ...


InventoryT = TypeVar("InventoryT", bound=SelectionInventory)


@dataclass(frozen=True, slots=True)
class NativeSelectionLayout:
    version: str
    tail_offset: int
    head_offset: int
    count_offset: int
    node_previous_offset: int
    node_next_offset: int
    node_unit_offset: int
    wrapper_type_offset: int
    wrapper_unit_type: int
    source: str

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


LOCAL_SELECTION_LAYOUT_127 = NativeSelectionLayout(
    version="1.27.0.52240",
    tail_offset=0x1F0,
    head_offset=0x1F4,
    count_offset=0x1F8,
    node_previous_offset=0,
    node_next_offset=4,
    node_unit_offset=8,
    wrapper_type_offset=0xC,
    wrapper_unit_type=0x2B61676C,
    source=(
        "Game.dll SHA256 e04d1716603c075eb0c8e1e21cf1093a664adc5249efab396bfa08d7b09d0c3a; "
        "1.27 local/async add 0x26FF80, remove 0x274C60, leader 0x2754B0; "
        "constructor 0x26EEB4..0x26EEE1; node links 0x271E80; "
        "UNIT uniqueness 0x26FBAA..0x26FBC1 / local caller 0x2700B8; "
        "unit wrapper role 0x1E6CAA..0x1E6CD4 (static byte proof)"
    ),
)


@dataclass(frozen=True, slots=True)
class SelectionEntry:
    ordinal: int
    entry_address: int
    next_address: int | None
    handle_address: int | None
    handle_lo: int | None
    handle_hi: int | None
    unit_address: int | None
    resolution: dict[str, int]
    diagnostics: tuple[str, ...]
    kind: str = "local-selection-node"
    unit_pointer_address: int | None = None
    next_pointer_address: int | None = None
    previous_address: int | None = None
    raw_node_bytes: str | None = None

    def to_dict(self) -> dict[str, object]:
        result = asdict(self)
        result["diagnostics"] = list(self.diagnostics)
        return result


@dataclass(frozen=True, slots=True)
class SelectionResult(Generic[InventoryT]):
    units: tuple[InventoryT, ...]
    complete: bool
    diagnostics: tuple[str, ...]
    entries: tuple[SelectionEntry, ...]
    context: dict[str, int]
    primary_unit: InventoryT | None = None
    primary_evidence: SelectionEntry | None = None
    layout: NativeSelectionLayout | None = None


def collect_selected_units(
    reader: SelectionReader,
    system: SelectionResolver,
    offsets: SelectionOffsets,
    dll_base: int,
    *,
    heap_lo: int,
    heap_hi: int,
    read_inventory: Callable[[int], InventoryT],
    layout: NativeSelectionLayout | None = None,
    primary_only: bool = False,
) -> SelectionResult[InventoryT]:
    """Read primary identity independently of the counted local/UI container.

    The primary field is a CUnit pointer. Its first DWORD is a vtable and is
    never a successor. Distinct 12-byte nodes have proved previous/next/unit
    roles, count/tail witnesses and a complemented-header terminal. No memory
    allocation or iteration budget is inferred from the count. Repeated UNIT
    identities violate the native insertion rule and stay diagnostic evidence.
    """
    diagnostics: list[str] = []
    context: dict[str, int] = {}
    entries: list[SelectionEntry] = []
    units: list[InventoryT] = []
    primary: InventoryT | None = None
    primary_evidence: SelectionEntry | None = None
    seen_units: set[int] = set()
    first_unit_nodes: dict[int, tuple[int, int]] = {}

    def result() -> SelectionResult[InventoryT]:
        return SelectionResult(
            tuple(units),
            not diagnostics,
            tuple(diagnostics),
            tuple(entries),
            context,
            primary,
            primary_evidence,
            layout,
        )

    def integer(address: int, key: str, *, size: int = 4) -> int | None:
        context[key + "_address"] = address
        raw = reader.read(address, size)
        if raw is None or len(raw) != size:
            diagnostics.append(f"选择源 {key} 不可读 @0x{address:X}")
            return None
        value = int.from_bytes(raw, "little")
        context[key] = value
        return value

    def valid_pointer(value: int | None) -> bool:
        return value is not None and heap_lo <= value < heap_hi

    def pointer(address: int, key: str, *, allow_null: bool = False) -> int | None:
        value = integer(address, key)
        if value == 0 and allow_null:
            return 0
        if value is not None and not valid_pointer(value):
            diagnostics.append(f"选择源 {key} 地址无效: 0x{value:X} @0x{address:X}")
            return None
        return value

    def resolve_unit(
        unit: int, *, require_type: bool
    ) -> tuple[InventoryT | None, int | None, int | None, dict[str, int], list[str]]:
        issues: list[str] = []
        if not valid_pointer(unit):
            return None, None, None, {}, [f"单位指针无效: 0x{unit:X}"]
        pair_address = unit + offsets.entry_pair_off
        pair = reader.read(pair_address, 8)
        if pair is None:
            return None, None, None, {}, [f"单位自身句柄对不可读 @0x{pair_address:X}"]
        lo, hi = struct.unpack("<II", pair)
        obj, evidence, failures = system.resolve_evidence(lo, hi)
        issues.extend(failures)
        if obj is not None and obj != unit:
            issues.append(f"单位自身句柄回链不符: 指针 0x{unit:X}, 回链 0x{obj:X}")
        if require_type and layout is not None and "wrapper_address" in evidence:
            type_address = evidence["wrapper_address"] + layout.wrapper_type_offset
            evidence["wrapper_type_address"] = type_address
            raw_type = reader.read(type_address, 4)
            if raw_type is None:
                issues.append(f"单位包装类别不可读 @0x{type_address:X}")
            else:
                actual_type = int.from_bytes(raw_type, "little")
                evidence["wrapper_type"] = actual_type
                if actual_type != layout.wrapper_unit_type:
                    issues.append(
                        f"单位包装类别未确认: 0x{actual_type:X} @0x{type_address:X}"
                    )
        if obj is None or issues:
            return None, lo, hi, evidence, issues
        inventory = read_inventory(unit)
        if not inventory.code:
            issues.extend(inventory.diagnostics)
            return None, lo, hi, evidence, issues
        return inventory, lo, hi, evidence, issues

    vmctx = pointer(dll_base + offsets.vmctx_global_rva, "vmctx")
    if vmctx is None:
        return result()
    player = integer(vmctx + offsets.player_idx_off, "local_player", size=2)
    if player is None:
        return result()
    if player >= 16:
        diagnostics.append(f"选择源本地玩家槽号无效: {player}")
        return result()
    pctx = pointer(vmctx + offsets.pctx_array_off + player * 4, "player_context")
    if pctx is None:
        return result()
    manager = pointer(pctx + offsets.selmgr_off, "selection_manager")
    if manager is None:
        return result()
    primary_pointer = pointer(
        manager + offsets.sel_entry_off, "primary_unit", allow_null=True
    )
    if primary_pointer:
        primary, lo, hi, evidence, issues = resolve_unit(
            primary_pointer, require_type=layout is not None
        )
        primary_evidence = SelectionEntry(
            -1,
            primary_pointer,
            None,
            primary_pointer + offsets.entry_pair_off,
            lo,
            hi,
            primary_pointer,
            evidence,
            tuple(issues),
            kind="primary-unit",
            unit_pointer_address=manager + offsets.sel_entry_off,
        )
        diagnostics.extend(f"主选中单位: {issue}" for issue in issues)
    if primary_only:
        if primary is not None:
            units.append(primary)
        diagnostics.append("仅解析主选中单位，未请求遍历本地选择集合")
        return result()
    if layout is None:
        if primary is not None:
            units.append(primary)
        diagnostics.append(
            "当前档案没有独立验证的完整本地选择集合布局；仅保留主选中单位证据"
        )
        return result()

    header = manager + layout.tail_offset
    terminal = (~header) & 0xFFFFFFFF
    context["local_header"] = header
    context["expected_terminal"] = terminal
    declared_count = integer(manager + layout.count_offset, "local_count")
    tail = integer(header, "local_tail")
    entry = integer(manager + layout.head_offset, "local_head")
    seen_nodes: set[int] = set()
    previous = header
    terminal_word: int | None = None
    while entry is not None:
        if entry == terminal:
            terminal_word = entry
            break
        if entry == 0 or entry & 0x80000000:
            terminal_word = entry
            diagnostics.append(
                f"本地选择尾标记不符: 0x{entry:X}, 期望补码哨兵 0x{terminal:X}"
            )
            break
        if not valid_pointer(entry):
            diagnostics.append(f"本地选择节点地址无效: 0x{entry:X}")
            break
        if entry in seen_nodes:
            diagnostics.append(f"本地选择节点循环: 0x{entry:X}")
            break
        seen_nodes.add(entry)
        ordinal = len(entries)
        issues: list[str] = []
        raw_previous = reader.read(entry + layout.node_previous_offset, 4)
        encoded_previous = (
            int.from_bytes(raw_previous, "little") if raw_previous is not None else None
        )
        if encoded_previous is None:
            issues.append(f"前驱指针不可读 @0x{entry + layout.node_previous_offset:X}")
        elif encoded_previous != previous:
            issues.append(f"前驱回链不符: 0x{encoded_previous:X}, 期望 0x{previous:X}")
        next_address = entry + layout.node_next_offset
        raw_next = reader.read(next_address, 4)
        following = int.from_bytes(raw_next, "little") if raw_next is not None else None
        if following is None:
            issues.append(f"后继指针不可读 @0x{next_address:X}")
        unit_pointer_address = entry + layout.node_unit_offset
        raw_unit = reader.read(unit_pointer_address, 4)
        unit = int.from_bytes(raw_unit, "little") if raw_unit is not None else None
        lo: int | None = None
        hi: int | None = None
        resolution: dict[str, int] = {}
        if unit is None:
            issues.append(f"单位指针不可读 @0x{unit_pointer_address:X}")
        else:
            inventory, lo, hi, resolution, failures = resolve_unit(
                unit, require_type=True
            )
            issues.extend(failures)
            if inventory is not None:
                if unit in seen_units:
                    first_ordinal, first_node = first_unit_nodes[unit]
                    issues.append(
                        f"重复 UNIT 0x{unit:X}: 首见于节点 {first_ordinal + 1} "
                        f"@0x{first_node:X}；保留本节点证据，完整性未确认"
                    )
                else:
                    seen_units.add(unit)
                    first_unit_nodes[unit] = (ordinal, entry)
                    units.append(inventory)
        raw_node = reader.read(entry, 12)
        entries.append(
            SelectionEntry(
                ordinal,
                entry,
                following,
                unit + offsets.entry_pair_off
                if valid_pointer(unit) and unit is not None
                else None,
                lo,
                hi,
                unit,
                resolution,
                tuple(issues),
                unit_pointer_address=unit_pointer_address,
                next_pointer_address=next_address,
                previous_address=encoded_previous,
                raw_node_bytes=raw_node.hex() if raw_node is not None else None,
            )
        )
        diagnostics.extend(
            f"本地选择节点 {ordinal + 1} @0x{entry:X}: {issue}" for issue in issues
        )
        previous, entry = entry, following
    context["observed_node_count"] = len(entries)
    if terminal_word is not None:
        context["terminal_word"] = terminal_word
    if declared_count is not None and declared_count != len(entries):
        diagnostics.append(
            f"本地选择数量不符: 声明 {declared_count}, 确认读取节点 {len(entries)}"
        )
    if tail is not None and tail != previous:
        diagnostics.append(f"本地选择尾指针不符: 0x{tail:X}, 期望 0x{previous:X}")
    if primary is not None and primary_pointer not in seen_units:
        diagnostics.append(
            "主选中单位不在已读取的本地选择集合中；保留独立主指针冲突证据，不并入本地集合"
        )
    return result()
