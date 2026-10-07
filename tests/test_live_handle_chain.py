# -*- coding: utf-8 -*-
"""live_handle_chain 合成内存回归测试。

用假区域复刻真实引擎结构: 句柄管理器双表 + 包装对象 + 选中链 + 单位背包。
偏移全部按 HANDLE_CHAIN_OFFSETS["1.27.0.52240"] 布置, 验证纯逻辑链路。
"""

from __future__ import annotations

import struct

from w3xtool.live_handle_chain import (
    HANDLE_CHAIN_OFFSETS,
    HandleSystem,
    MemoryReader,
    classic_template,
    derive_offsets,
    fourcc,
    is_fourcc,
    read_inventory,
    reader_from_snapshot,
    selected_unit,
    walk_item_units,
)

DLL_BASE = 0x782C0000


def _build_memory():
    """构造: 一个选中英雄(2件物品) + 一个满装单位 + 一个空背包单位 + 噪声对象。"""
    o = HANDLE_CHAIN_OFFSETS["1.27.0.52240"]
    blobs: dict[int, bytearray] = {}

    def put(addr, data):
        blobs.setdefault(addr & 0xFFFFF000, bytearray()).extend(b"")  # placeholder
        base = addr
        blobs[base] = bytearray(data)

    # 用显式地址拼内存: 每个结构单独一段
    def seg(addr, payload):
        blobs[addr] = bytearray(payload)

    def dwords(*vals):
        return b"".join(struct.pack("<I", v & 0xFFFFFFFF) for v in vals)

    def code_dword(code: bytes) -> int:
        # 引擎在内存中按大端语义存四码: "I021" -> dword 0x49303231
        return struct.unpack(">I", code)[0]

    # --- 物品对象: +0x30 类型四码 (大端 dword) ---
    ITEM_A = 0x10000000  # I021
    ITEM_B = 0x10000100  # I01F
    ITEM_C = 0x10000200  # I07F
    for addr, code in ((ITEM_A, b"I021"), (ITEM_B, b"I01F"), (ITEM_C, b"I07F")):
        seg(addr, dwords(0xDEADBE00, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0, code_dword(code)))

    # --- 背包: 槽区 +0x70, 槽距 12, 句柄对 {lo, hi} ---
    INV_SEL = 0x10010000
    slots = bytearray(0x70 + 12 * 6)
    struct.pack_into("<II", slots, 0x70 + 0, 0x11, 0xAA)  # 槽0 -> ITEM_A
    struct.pack_into("<II", slots, 0x70 + 12, 0x12, 0xBB)  # 槽1 -> ITEM_B
    struct.pack_into("<II", slots, 0x70 + 24, 0xFFFFFFFF, 0xFFFFFFFF)  # 槽2 空
    struct.pack_into("<II", slots, 0x70 + 36, 0, 0)  # 槽3 空
    seg(INV_SEL, bytes(slots))

    INV_FULL = 0x10020000
    slots2 = bytearray(0x70 + 12 * 6)
    for k in range(3):
        struct.pack_into("<II", slots2, 0x70 + 12 * k, 0x21 + k, 0xCC + k)
    struct.pack_into("<II", slots2, 0x70 + 36, 0xFFFFFFFF, 0xFFFFFFFF)
    seg(INV_FULL, bytes(slots2))

    INV_EMPTY = 0x10030000
    seg(INV_EMPTY, b"\xff" * (0x70 + 12 * 6))

    # --- 单位: +0x30 类型四码, +0x1F8 背包指针 ---
    HERO = 0x20000000  # H004
    OTHER = 0x20001000  # N02A
    EMPTY_U = 0x20002000  # h00X (空背包)
    for addr, code, inv in (
        (HERO, b"H004", INV_SEL),
        (OTHER, b"N02A", INV_FULL),
        (EMPTY_U, b"h00X", INV_EMPTY),
    ):
        body = bytearray(0x200)
        struct.pack_into("<I", body, 0x30, code_dword(code))
        struct.pack_into("<I", body, 0x1F8, inv)
        seg(addr, bytes(body))

    # --- 包装对象: +0x18 世代, +0x20 存活标志, +0x54 对象 ---
    def wrapper(addr, gen, obj):
        body = bytearray(0x60)
        struct.pack_into("<I", body, 0x18, gen)
        struct.pack_into("<I", body, 0x20, 0)
        struct.pack_into("<I", body, 0x54, obj)
        seg(addr, bytes(body))

    W_HERO, W_OTHER, W_EMPTY = 0x30000000, 0x30000100, 0x30000200
    W_IA, W_IB = 0x30010000, 0x30010100
    W_IC1, W_IC2, W_IC3 = 0x30010200, 0x30010300, 0x30010400
    wrapper(W_HERO, 0x5001, HERO)
    wrapper(W_OTHER, 0x5002, OTHER)
    wrapper(W_EMPTY, 0x5003, EMPTY_U)
    wrapper(W_IA, 0xAA, ITEM_A)
    wrapper(W_IB, 0xBB, ITEM_B)
    wrapper(W_IC1, 0xCC, ITEM_C)
    wrapper(W_IC2, 0xCD, ITEM_C)
    wrapper(W_IC3, 0xCE, ITEM_C)

    # --- 句柄管理器双表: 8 字节条目 {标记, 包装} ---
    TAB_A = 0x40000000
    entries_a = bytearray(8 * 64)
    struct.pack_into("<II", entries_a, 0x11 * 8, 0xFFFFFFFE, W_IA)
    struct.pack_into("<II", entries_a, 0x12 * 8, 0xFFFFFFFE, W_IB)
    struct.pack_into("<II", entries_a, 0x21 * 8, 0xFFFFFFFE, W_IC1)
    struct.pack_into("<II", entries_a, 0x22 * 8, 0xFFFFFFFE, W_IC2)
    struct.pack_into("<II", entries_a, 0x23 * 8, 0xFFFFFFFE, W_IC3)
    seg(TAB_A, bytes(entries_a))

    TAB_B = 0x40010000
    entries_b = bytearray(8 * 64)
    # bit31=1 的句柄: 选中条目用 (0x80000000 | 7)
    struct.pack_into("<II", entries_b, 7 * 8, 0xFFFFFFFE, W_HERO)
    struct.pack_into("<II", entries_b, 8 * 8, 0xFFFFFFFE, W_OTHER)
    struct.pack_into("<II", entries_b, 9 * 8, 0xFFFFFFFE, W_EMPTY)
    seg(TAB_B, bytes(entries_b))

    HM = 0x1B3A0000
    hm_body = bytearray(0x40)
    struct.pack_into("<I", hm_body, o.hm_tableA_base_off, TAB_A)
    struct.pack_into("<I", hm_body, o.hm_tableA_bound_off, 64)
    struct.pack_into("<I", hm_body, o.hm_tableB_base_off, TAB_B)
    struct.pack_into("<I", hm_body, o.hm_tableB_bound_off, 64)
    seg(HM, bytes(hm_body))

    # --- 全局 (dll .data): 句柄管理器 + vmctx ---
    seg(DLL_BASE + o.handle_mgr_global_rva, dwords(HM))
    VMCTX = 0x1B400000
    seg(DLL_BASE + o.vmctx_global_rva, dwords(VMCTX))
    vm = bytearray(0x80)
    struct.pack_into("<H", vm, o.player_idx_off, 1)
    struct.pack_into("<I", vm, o.pctx_array_off + 1 * 4, 0x1B500000)
    seg(VMCTX, bytes(vm))

    PCTX = 0x1B500000
    pc = bytearray(0x40)
    struct.pack_into("<I", pc, o.selmgr_off, 0x1B600000)
    seg(PCTX, bytes(pc))

    SELMGR = 0x1B600000
    sm = bytearray(0x200)
    struct.pack_into("<I", sm, o.sel_entry_off, 0x1B700000)
    seg(SELMGR, bytes(sm))

    ENTRY = 0x1B700000
    ent = bytearray(0x20)
    struct.pack_into("<I", ent, 0, 0)  # 链表结束
    struct.pack_into("<I", ent, o.entry_pair_off, 0x80000007)
    struct.pack_into("<I", ent, o.entry_pair_off + 4, 0x5001)
    seg(ENTRY, bytes(ent))

    regions = [(base, bytes(blob)) for base, blob in blobs.items()]
    return regions, HERO, OTHER, o


def test_fourcc_roundtrip():
    assert fourcc(struct.unpack(">I", b"I021")[0]) == "I021"
    assert fourcc(0x48303147) == "H01G"
    assert is_fourcc("I021")
    assert not is_fourcc("?\x00\x01")
    assert not is_fourcc(123)


def test_offsets_table_complete():
    o = HANDLE_CHAIN_OFFSETS["1.27.0.52240"]
    assert o.vmctx_global_rva == 0xBE4238
    assert o.handle_mgr_global_rva == 0xBE40A8
    assert o.inv_slots_off == 0x70 and o.inv_slot_stride == 12
    assert o.unit_inv_off == 0x1F8 and o.wrapper_obj_off == 0x54


def test_resolve_and_inventory():
    regions, hero, _other, o = _build_memory()
    reader = MemoryReader(regions)
    system = HandleSystem(reader, DLL_BASE, o)
    assert system.valid
    inv = read_inventory(reader, system, o, hero)
    assert inv.code == "H004"
    codes = [(i.slot, i.code) for i in inv.items]
    assert codes == [(0, "I021"), (1, "I01F")]


def test_selected_unit():
    regions, hero, _other, o = _build_memory()
    reader = MemoryReader(regions)
    system = HandleSystem(reader, DLL_BASE, o)
    sel = selected_unit(reader, system, o, DLL_BASE)
    assert sel is not None
    assert sel.code == "H004"
    assert [i.code for i in sel.items] == ["I021", "I01F"]


def test_walk_item_units_orders_by_count():
    regions, _hero, other, o = _build_memory()
    reader = MemoryReader(regions)
    system = HandleSystem(reader, DLL_BASE, o)
    units = walk_item_units(reader, system, o)
    codes = [u.code for u in units]
    assert codes[0] == "N02A"  # 3 件排最前
    assert "H004" in codes
    assert all(u.items for u in units)  # 空背包单位被过滤


def test_classic_template_zero_rvas():
    t = classic_template()
    assert t.vmctx_global_rva == 0
    assert t.handle_mgr_global_rva == 0
    known = HANDLE_CHAIN_OFFSETS["1.27.0.52240"]
    assert t.player_idx_off == known.player_idx_off
    assert t.unit_inv_off == known.unit_inv_off


def test_derive_offsets_rediscovers_globals():
    """不喂版本表: 纯结构特征应重新找到两个全局槽并走通选中链。"""
    regions, _hero, _other, o = _build_memory()
    reader = MemoryReader(regions)
    derived = derive_offsets(reader, DLL_BASE, DLL_BASE + 0x2000000)
    assert derived is not None
    assert derived.handle_mgr_global_rva == o.handle_mgr_global_rva
    assert derived.vmctx_global_rva == o.vmctx_global_rva
    system = HandleSystem(reader, DLL_BASE, derived)
    assert system.valid
    sel = selected_unit(reader, system, derived, DLL_BASE)
    assert sel is not None and sel.code == "H004"


def test_derive_offsets_returns_none_without_structures():
    reader = MemoryReader([(0x50000000, b"\x00" * 0x1000)])
    assert derive_offsets(reader, 0x50000000, 0x50001000) is None


def test_reader_from_snapshot_unpacks_regions_tuple():
    """回归: snapshot() 返回 (regions, total) 二元组。

    直接把该元组传给 MemoryReader 会把区域列表当二元组迭代, 真实进程中以
    "too many values to unpack" 崩溃 (差分快照路径)。
    """
    regions = [(0x20000000, b"\x00" * 0x100), (0x20010000, b"\xff" * 0x100)]
    reader = reader_from_snapshot((regions, 0x200))
    assert reader.read(0x20000000, 4) == b"\x00\x00\x00\x00"
    assert reader.read(0x20010000, 2) == b"\xff\xff"
    assert reader.read(0x90000000, 4) is None
