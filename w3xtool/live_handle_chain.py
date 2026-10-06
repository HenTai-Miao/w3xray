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
import math
import re
import struct
from dataclasses import dataclass, field, replace

__all__ = (
    "LiveHandleOffsets",
    "HANDLE_CHAIN_OFFSETS",
    "MemoryReader",
    "HandleSystem",
    "OwnedUnit",
    "PlayerResources",
    "UNIT_OWNER_OFF",
    "UNIT_POS_X_OFF",
    "UNIT_POS_Y_OFF",
    "fourcc",
    "is_fourcc",
    "read_inventory",
    "walk_item_units",
    "read_unit_owner",
    "read_unit_pos",
    "walk_owned_units",
    "summarize_owners",
    "find_resource_layout",
    "selected_unit",
    "match_unit_entries",
    "classic_template",
    "derive_offsets",
)

# 单位结构内的所属玩家与坐标字段偏移 (1.27.0.52240/KK 实测验证):
# 所有者为单字节玩家号 0..15; 坐标为两个相邻 float (X 东正, Y 北正)。
UNIT_OWNER_OFF = 0x58
UNIT_POS_X_OFF = 0x284
UNIT_POS_Y_OFF = 0x288
# 坐标合理上限 (超出视为解析失败而不是游戏坐标)。
_POS_SPAN_LIMIT = 200000.0

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


def classic_template() -> LiveHandleOffsets:
    """经典引擎 (1.24~1.27 家族) 的结构字段偏移模板。

    同族版本的结构字段布局稳定, 版本差异集中在两个全局变量的 RVA;
    RVA 由 derive_offsets() 在运行内存中按结构特征自动识别。
    """
    known = HANDLE_CHAIN_OFFSETS.get("1.27.0.52240")
    if known is not None:
        return replace(
            known, vmctx_global_rva=0, handle_mgr_global_rva=0, source="classic 模板"
        )
    return LiveHandleOffsets(
        vmctx_global_rva=0,
        handle_mgr_global_rva=0,
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
        source="classic 模板",
    )


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

    def iter_regions(self):
        """按基址升序产出 (基址, 字节块)。"""
        for base in self._bases:
            yield base, self._data[base]


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


@dataclass(frozen=True, slots=True)
class OwnedUnit:
    """一个存活单位: 地址、四码、所属玩家号与坐标。"""

    addr: int
    code: str
    owner: int
    x: float
    y: float


def read_unit_owner(reader: MemoryReader, addr: int) -> int:
    """单位所属玩家号 (0..15); 读不到返回 -1。"""
    raw = reader.read(addr + UNIT_OWNER_OFF, 1)
    return raw[0] if raw else -1


def read_unit_pos(reader: MemoryReader, addr: int) -> tuple[float, float]:
    """单位坐标 (X 东正, Y 北正); 不合理或读不到返回 (0.0, 0.0)。"""
    raw = reader.read(addr + UNIT_POS_X_OFF, 8)
    if not raw:
        return (0.0, 0.0)
    x, y = struct.unpack("<ff", raw)
    if abs(x) > _POS_SPAN_LIMIT or abs(y) > _POS_SPAN_LIMIT:
        return (0.0, 0.0)
    return (x, y)


def walk_owned_units(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
    max_units: int = 8000,
) -> list[OwnedUnit]:
    """全对象扫描, 返回所有带合法四码且所有者可读的单位 (含地图物件)。"""
    units: list[OwnedUnit] = []
    for obj in system.live_objects():
        code = fourcc(reader.u32(obj + o.unit_type_off))
        if not is_fourcc(code):
            continue
        owner = read_unit_owner(reader, obj)
        if not 0 <= owner <= 15:
            continue
        x, y = read_unit_pos(reader, obj)
        units.append(OwnedUnit(obj, code, owner, x, y))
        if len(units) >= max_units:
            break
    return units


def summarize_owners(
    units: list[OwnedUnit], list_cap: int = 8
) -> tuple[dict[int, int], list[OwnedUnit]]:
    """按所有者汇总: (每个玩家号的数量, 数量<=list_cap 的玩家号下全部单位)。

    地图生成的物件通常集中在少数玩家号 (如中立 8/地形 0) 且数量巨大;
    真人玩家的单位挂在各自玩家号下数量很少, 低于 list_cap 即逐个列出。
    """
    counts: dict[int, int] = {}
    for u in units:
        counts[u.owner] = counts.get(u.owner, 0) + 1
    small = {owner for owner, n in counts.items() if n <= list_cap}
    listed = [u for u in units if u.owner in small]
    listed.sort(key=lambda u: (u.owner, u.code, round(u.x), round(u.y)))
    return counts, listed


@dataclass(frozen=True, slots=True)
class PlayerResources:
    """一个玩家资源结构: 结构地址 + 金币/木材 (+人口尽力识别)。"""

    addr: int
    gold: float
    lumber: float
    food: int | None = None


def _plausible_resource(f: float) -> bool:
    """资源值特征: 有限、非负、近整数的常规数量级。"""
    return math.isfinite(f) and 0 <= f < 10_000_000 and abs(f - round(f)) < 0.001


def _iter_float_slots(reader: "MemoryReader"):
    """遍历全部区域的 (地址, float 值); 只产出资源量级的候选。"""
    for base_a, data in reader._data.items():
        if len(data) < 0x100:
            continue
        for off in range(0, len(data) - 4, 4):
            f = struct.unpack_from("<f", data, off)[0]
            if _plausible_resource(f):
                yield base_a + off, f


def find_resource_layout(
    reader: "MemoryReader", gold: float, lumber: float, window: int = 0x100
) -> list[PlayerResources]:
    """以当前已知的一组 金币/木材 数值为锚, 定位同布局的玩家资源结构列表。

    原理: 精确匹配金币 float; 在 +/- window 内找木材 float; 同一
    (金币->木材) 相对偏移的其余结构即为其他玩家/缓存副本。引擎为每个
    玩家维护同构资源结构, 布局一致而地址不同。
    """
    gold_addr = []
    lumber_addr = []
    for addr, f in _iter_float_slots(reader):
        if f == gold:
            gold_addr.append(addr)
        elif f == lumber:
            lumber_addr.append(addr)
    pairs: list[tuple[int, int]] = []
    for g in gold_addr:
        for lum in lumber_addr:
            delta = lum - g
            if 0 < abs(delta) <= window and delta % 4 == 0:
                pairs.append((g, delta))
    if not pairs:
        return []
    delta_counts: dict[int, int] = {}
    for _, d in pairs:
        delta_counts[d] = delta_counts.get(d, 0) + 1
    best_delta = max(delta_counts, key=lambda d: delta_counts[d])
    anchors = sorted(g for g, d in pairs if d == best_delta)
    out: list[PlayerResources] = []
    for g in anchors:
        food = None
        for fo in (best_delta + 4, best_delta + 8, best_delta - 4, 4, 8):
            raw = reader.read(g + fo, 4)
            if not raw:
                continue
            fv = struct.unpack("<f", raw)[0]
            if _plausible_resource(fv) and round(fv) <= 1000:
                food = round(fv)
                break
        out.append(PlayerResources(g, gold, lumber, food))
    return out


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


def _looks_like_handle_manager(
    reader: MemoryReader, hm: int, o: LiveHandleOffsets
) -> bool:
    """结构校验: 双表指针入堆、bound 合理、且能找到存活的包装条目。"""
    hits = 0
    for base_off, bound_off in (
        (o.hm_tableA_base_off, o.hm_tableA_bound_off),
        (o.hm_tableB_base_off, o.hm_tableB_bound_off),
    ):
        base = reader.u32(hm + base_off)
        bound = reader.u32(hm + bound_off)
        if not (_HEAP_LO <= base < _HEAP_HI) or not (0 < bound < 0x200000):
            return False
        for index in range(min(bound, 128)):
            if reader.u32(base + index * 8) != 0xFFFFFFFE:
                continue
            wrapper = reader.u32(base + index * 8 + 4)
            if not (_HEAP_LO <= wrapper < _HEAP_HI):
                continue
            if reader.u32(wrapper + o.wrapper_alive_off) != 0:
                continue
            obj = reader.u32(wrapper + o.wrapper_obj_off)
            if _HEAP_LO <= obj < _HEAP_HI:
                hits += 1
                if hits >= 2:
                    return True
    return False


def _selection_chain_valid(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
    vmctx: int,
    require_inventory: bool = True,
) -> bool:
    """端到端校验: 从候选 vmctx 走选中链, 解析出一个带合法四码的单位。

    严格模式 (require_inventory) 额外要求该单位带背包对象, 并要求
    vmctx+0x28 的本地玩家号落在 0..15 —— 用于排除结构巧合的假阳性。
    """
    if reader.u16(vmctx + o.player_idx_off) >= 16:
        return False
    for player in range(16):
        pctx = reader.u32(vmctx + o.pctx_array_off + player * 4)
        if not (_HEAP_LO <= pctx < _HEAP_HI):
            continue
        selmgr = reader.u32(pctx + o.selmgr_off)
        if not (_HEAP_LO <= selmgr < _HEAP_HI):
            continue
        entry = reader.u32(selmgr + o.sel_entry_off)
        for _ in range(12):
            if not (_HEAP_LO <= entry < _HEAP_HI):
                break
            lo = reader.u32(entry + o.entry_pair_off)
            hi = reader.u32(entry + o.entry_pair_off + 4)
            unit = system.resolve(lo, hi)
            if unit is not None and is_fourcc(
                fourcc(reader.u32(unit + o.unit_type_off))
            ):
                if require_inventory:
                    inv = reader.u32(unit + o.unit_inv_off)
                    if not (_HEAP_LO <= inv < _HEAP_HI):
                        continue
                return True
            entry = reader.u32(entry)
    return False


def _iter_dwords(reader: MemoryReader, lo: int, hi: int):
    """产出 [lo, hi) 内可读的 (地址, dword 值), 按区域分块。"""
    for base, blob in reader.iter_regions():
        if base + len(blob) <= lo or base >= hi:
            continue
        start = max(lo, base) - base
        end = min(hi, base + len(blob)) - base
        for off in range(start & ~3, end - 3, 4):
            yield base + off, struct.unpack_from("<I", blob, off)[0]


def derive_offsets(
    reader: MemoryReader,
    dll_base: int,
    dll_end: int,
    scan_limit: int = 0x4000000,
    max_hm_candidates: int = 8,
) -> LiveHandleOffsets | None:
    """在 Game.dll 内存中按结构特征自动识别两个全局槽, 生成偏移表。

    不依赖版本号或硬编码 RVA: 先收集"长得像句柄管理器"的候选,
    逐个构建句柄系统并用选中链端到端验证, 全部通过才算成功
    (避免先遇到的假阳性候选导致整体失败)。
    适用于经典引擎家族; 失败返回 None (调用方回退其它策略)。
    """
    hi = min(dll_end, dll_base + scan_limit)
    if hi <= dll_base:
        return None
    tpl = classic_template()
    hm_candidates: list[tuple[int, int]] = []
    seen_managers: set[int] = set()
    for addr, value in _iter_dwords(reader, dll_base, hi):
        if (
            _HEAP_LO <= value < _HEAP_HI
            and value not in seen_managers
            and _looks_like_handle_manager(reader, value, tpl)
        ):
            seen_managers.add(value)
            hm_candidates.append((addr, value))
            if len(hm_candidates) >= max_hm_candidates:
                break
    systems: list[tuple[LiveHandleOffsets, HandleSystem]] = []
    for hm_slot, _hm in hm_candidates:
        stage = replace(tpl, handle_mgr_global_rva=hm_slot - dll_base)
        system = HandleSystem(reader, dll_base, stage)
        if system.valid:
            systems.append((stage, system))
    # 先全员严格校验 (要求玩家号合法 + 选中单位带背包), 再放宽到四码即可。
    for require_inventory in (True, False):
        for stage, system in systems:
            for addr, value in _iter_dwords(reader, dll_base, hi):
                if not (_HEAP_LO <= value < _HEAP_HI):
                    continue
                if _selection_chain_valid(
                    reader, system, tpl, value, require_inventory
                ):
                    return replace(
                        stage,
                        vmctx_global_rva=addr - dll_base,
                        source="结构特征自动推导 (classic 模板)",
                    )
    return None


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
