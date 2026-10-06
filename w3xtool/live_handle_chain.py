# -*- coding: utf-8 -*-
"""live_handle_chain: 经典 1.27 句柄系统 → 选中单位 → 背包 只读链。

全部结构偏移来自 Game.dll 原生函数静态反汇编验证 (capstone)，
运行路径: 只读 ReadProcessMemory 快照 regions + 纯 Python 遍历，不注入。

已验证链 (1.27.0.52240, KK 平台 Game.dll @0x782C0000):
  选择: [dll+0xBE4238]=vmctx → +0x28(字)=本地玩家号
        → [vmctx+0x58+玩家号*4]=玩家上下文 → +0x34=选中管理器
        → +0x1E0=当前选中条目 → +0xC/+0x10=句柄对
  句柄: [dll+0xBE40A8]=句柄管理器; 表A [hm+0xC]/上限[hm+0x1C] (bit31=0),
        表B [hm+0x2C]/上限[hm+0x3C] (bit31=1); 8 字节条目{标记,包装指针};
        包装: +0x18=世代(须等于句柄高字), +0x20=0 存活, +0x54=对象指针
  背包: 单位+0x30=类型四码, +0x1F8=背包指针;
        槽位 = 背包+0x70+12*k, 12 字节句柄对 [s]/[s+4],
        空 = (lo&hi)==0xFFFFFFFF 或 (lo|hi)==0; 物品+0x30=类型四码

版本适配: 换版本时对 Game.dll 重跑原生表定位 (名字串→条目→实现地址)
并重新反汇编 SelectUnit/ClearSelection/UnitItemInSlot 得到新偏移, 加入
HANDLE_CHAIN_OFFSETS 即可; 结构布局在经典引擎内高度稳定。
"""

from __future__ import annotations

import bisect
import re
import struct
from dataclasses import dataclass, field

__all__ = (
    "LiveHandleOffsets",
    "HANDLE_CHAIN_OFFSETS",
    "MemoryReader",
    "HandleSystem",
    "fourcc",
    "is_fourcc",
    "read_inventory",
    "walk_item_units",
    "selected_unit",
    "match_unit_entries",
)

_FOURCC_RE = re.compile(r"[A-Za-z][0-9A-Za-z]{3}")

# 可句柄化的游戏对象都落在引擎堆区间; 出界即视为解析失败。
_HEAP_LO = 0x08000000
_HEAP_HI = 0x60000000


@dataclass(frozen=True, slots=True)
class LiveHandleOffsets:
    """一个 Game.dll 版本的句柄链结构偏移 (RVA 或字段偏移)。"""

    vmctx_global_rva: int
    handle_mgr_global_rva: int
    player_idx_off: int
    pctx_array_off: int
    selmgr_off: int
    sel_entry_off: int
    entry_pair_off: int
    hm_tableA_base_off: int
    hm_tableA_bound_off: int
    hm_tableB_base_off: int
    hm_tableB_bound_off: int
    wrapper_gen_off: int
    wrapper_alive_off: int
    wrapper_obj_off: int
    unit_type_off: int
    unit_inv_off: int
    inv_slots_off: int
    inv_slot_stride: int
    item_type_off: int
    source: str = ""


HANDLE_CHAIN_OFFSETS: dict[str, LiveHandleOffsets] = {
    "1.27.0.52240": LiveHandleOffsets(
        vmctx_global_rva=0xBE4238,
        handle_mgr_global_rva=0xBE40A8,
        player_idx_off=0x28,
        pctx_array_off=0x58,
        selmgr_off=0x34,
        sel_entry_off=0x1E0,
        entry_pair_off=0xC,
        hm_tableA_base_off=0xC,
        hm_tableA_bound_off=0x1C,
        hm_tableB_base_off=0x2C,
        hm_tableB_bound_off=0x3C,
        wrapper_gen_off=0x18,
        wrapper_alive_off=0x20,
        wrapper_obj_off=0x54,
        unit_type_off=0x30,
        unit_inv_off=0x1F8,
        inv_slots_off=0x70,
        inv_slot_stride=12,
        item_type_off=0x30,
        source="Game.dll 1.27.0.52240 (KK) 反汇编验证",
    ),
}


def fourcc(dword: int) -> str:
    """把内存中的四码 dword (大端序) 转成字符串。"""
    return struct.pack(">I", dword & 0xFFFFFFFF).decode("latin-1")


def is_fourcc(code: object) -> bool:
    return isinstance(code, str) and _FOURCC_RE.fullmatch(code) is not None


class MemoryReader:
    """对 (基址, 字节) 区域列表的只读随机访问。"""

    def __init__(self, regions):
        pairs = [(int(base), bytes(data)) for base, data in regions if data]
        pairs.sort()
        self._data = dict(pairs)
        self._bases = [base for base, _ in pairs]

    def read(self, addr: int, size: int) -> bytes | None:
        index = bisect.bisect_right(self._bases, addr) - 1
        if index < 0:
            return None
        base = self._bases[index]
        off = addr - base
        blob = self._data[base]
        if off < 0 or off + size > len(blob):
            return None
        return blob[off : off + size]

    def u32(self, addr: int) -> int:
        raw = self.read(addr, 4)
        return struct.unpack("<I", raw)[0] if raw else 0

    def u16(self, addr: int) -> int:
        raw = self.read(addr, 2)
        return struct.unpack("<H", raw)[0] if raw else 0


@dataclass(frozen=True, slots=True)
class _Table:
    base: int
    bound: int


class HandleSystem:
    """句柄管理器双表: (低字, 高字) → 包装对象 → 真实对象指针。"""

    def __init__(self, reader: MemoryReader, dll_base: int, o: LiveHandleOffsets):
        self._r = reader
        self._o = o
        hm = reader.u32(dll_base + o.handle_mgr_global_rva)
        self.manager = hm if _HEAP_LO <= hm < _HEAP_HI else 0
        self.tables = (
            _Table(0, 0),
            _Table(0, 0),
        )
        if self.manager:
            self.tables = (
                _Table(
                    reader.u32(hm + o.hm_tableA_base_off),
                    reader.u32(hm + o.hm_tableA_bound_off),
                ),
                _Table(
                    reader.u32(hm + o.hm_tableB_base_off),
                    reader.u32(hm + o.hm_tableB_bound_off),
                ),
            )

    @property
    def valid(self) -> bool:
        return bool(self.manager) and all(
            t.base and 0 < t.bound < 0x200000 for t in self.tables
        )

    def resolve(self, lo: int, hi: int) -> int | None:
        """句柄对 → 对象地址; 失败返回 None。"""
        o = self._o
        r = self._r
        table = self.tables[(lo >> 0x1F) & 1]
        index = lo & 0x7FFFFFFF
        if index >= table.bound:
            return None
        wrapper = r.u32(table.base + index * 8 + 4)
        if not (_HEAP_LO <= wrapper < _HEAP_HI):
            return None
        if r.u32(wrapper + o.wrapper_gen_off) != hi:
            return None
        if r.u32(wrapper + o.wrapper_alive_off) != 0:
            return None
        obj = r.u32(wrapper + o.wrapper_obj_off)
        return obj if _HEAP_LO <= obj < _HEAP_HI else None

    def live_objects(self, limit: int = 400_000):
        """枚举句柄表中所有存活对象地址 (单位/物品/UI 混在一起)。"""
        o = self._o
        r = self._r
        found: list[int] = []
        for table in self.tables:
            if not table.base:
                continue
            for index in range(table.bound):
                if len(found) >= limit:
                    return found
                wrapper = r.u32(table.base + index * 8 + 4)
                if not (_HEAP_LO <= wrapper < _HEAP_HI):
                    continue
                if r.u32(wrapper + o.wrapper_alive_off) != 0:
                    continue
                obj = r.u32(wrapper + o.wrapper_obj_off)
                if _HEAP_LO <= obj < _HEAP_HI:
                    found.append(obj)
        return found


@dataclass(frozen=True, slots=True)
class SlotItem:
    """一格背包物品。"""

    slot: int
    item_addr: int
    code: str


@dataclass(frozen=True, slots=True)
class UnitInventory:
    """一个单位的类型四码与背包物品列表。"""

    unit_addr: int
    code: str
    items: tuple[SlotItem, ...] = field(default=())


def read_inventory(
    reader: MemoryReader, system: HandleSystem, o: LiveHandleOffsets, unit_addr: int
) -> UnitInventory:
    """读单位 +0x1F8 背包的 6 个槽位; 类型四码不可读时视为非单位。"""
    code = fourcc(reader.u32(unit_addr + o.unit_type_off))
    if not is_fourcc(code):
        return UnitInventory(unit_addr, "", ())
    inv = reader.u32(unit_addr + o.unit_inv_off)
    if not (_HEAP_LO <= inv < _HEAP_HI):
        return UnitInventory(unit_addr, code, ())
    items: list[SlotItem] = []
    for slot in range(6):
        s = inv + o.inv_slots_off + o.inv_slot_stride * slot
        lo = reader.u32(s)
        hi = reader.u32(s + 4)
        if (lo & hi) == 0xFFFFFFFF or (lo | hi) == 0:
            continue
        item = system.resolve(lo, hi)
        if item is None:
            continue
        item_code = fourcc(reader.u32(item + o.item_type_off))
        items.append(SlotItem(slot, item, item_code))
    return UnitInventory(unit_addr, code, tuple(items))


def walk_item_units(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
    max_units: int = 24,
) -> list[UnitInventory]:
    """全对象扫描, 返回带有效物品四码的单位 (英雄/宝宝/商店怪)。"""
    units: list[UnitInventory] = []
    for obj in system.live_objects():
        inv = UnitInventory(obj, "", ())
        code = fourcc(reader.u32(obj + o.unit_type_off))
        if not is_fourcc(code):
            continue
        inv_addr = reader.u32(obj + o.unit_inv_off)
        if not (_HEAP_LO <= inv_addr < _HEAP_HI):
            continue
        inv = read_inventory(reader, system, o, obj)
        valid = [i for i in inv.items if is_fourcc(i.code)]
        if valid:
            units.append(UnitInventory(obj, code, tuple(valid)))
        if len(units) >= max_units * 8:
            break
    units.sort(key=lambda u: -len(u.items))
    return units[:max_units]


def match_unit_entries(units, query):
    """按单位名子串或四码 (大小写不敏感) 过滤 handle 策略产出的单位条目。

    条目形如 {"unit": 名字, "code": 四码, "items": [...]}。
    四码全等优先 (如 H004); 否则名字双向子串匹配 (寒冰 -> 寒冰游侠)。
    """
    q = str(query).strip().lower()
    if not q:
        return list(units)
    by_code = [u for u in units if str(u.get("code", "")).lower() == q]
    if by_code:
        return by_code
    return [
        u
        for u in units
        if q in str(u.get("unit", "")).lower() or str(u.get("unit", "")).lower() in q
    ]


def selected_unit(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
    dll_base: int,
    max_walk: int = 12,
) -> UnitInventory | None:
    """读当前选中单位 (选择链), 失败/未选中返回 None。"""
    vmctx = reader.u32(dll_base + o.vmctx_global_rva)
    if not (_HEAP_LO <= vmctx < _HEAP_HI):
        return None
    player = reader.u16(vmctx + o.player_idx_off)
    pctx = reader.u32(vmctx + o.pctx_array_off + player * 4)
    if not (_HEAP_LO <= pctx < _HEAP_HI):
        return None
    selmgr = reader.u32(pctx + o.selmgr_off)
    if not (_HEAP_LO <= selmgr < _HEAP_HI):
        return None
    entry = reader.u32(selmgr + o.sel_entry_off)
    for _ in range(max_walk):
        if not (_HEAP_LO <= entry < _HEAP_HI):
            break
        lo = reader.u32(entry + o.entry_pair_off)
        hi = reader.u32(entry + o.entry_pair_off + 4)
        unit = system.resolve(lo, hi)
        if unit is not None:
            inv = read_inventory(reader, system, o, unit)
            if inv.code:
                return inv
        entry = reader.u32(entry)
    return None
