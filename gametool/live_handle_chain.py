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
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field, replace
from typing import Any

__all__ = (
    "BUILD_PROFILES",
    "DERIVE_STAGES",
    "HANDLE_CHAIN_OFFSETS",
    "LIVE_PROFILE_ID",
    "UNIT_FIELD_LAYOUT",
    "UNIT_OWNER_OFF",
    "UNIT_POS_X_OFF",
    "UNIT_POS_Y_OFF",
    "DiscoveryStage",
    "HandleSystem",
    "LiveBuildProfile",
    "LiveHandleOffsets",
    "MemoryReader",
    "OwnedUnit",
    "PlayerResources",
    "ScanBudget",
    "cached_resource_hit",
    "classic_template",
    "derive_offsets",
    "describe_live_profile",
    "find_auto_resource_rows",
    "find_resource_layout",
    "fourcc",
    "is_fourcc",
    "match_unit_entries",
    "profile_from_dict",
    "profile_to_dict",
    "read_inventory",
    "read_player_resources_chain",
    "read_unit_owner",
    "read_unit_pos",
    "resolve_profile",
    "selected_unit",
    "summarize_owners",
    "walk_item_units",
    "walk_owned_units",
)

# 单位结构内的所属玩家与坐标字段偏移 (1.27.0.52240/KK 实测验证):
# 所有者为单字节玩家号 0..15; 坐标为两个相邻 float (X 东正, Y 北正)。
UNIT_OWNER_OFF = 0x58
UNIT_POS_X_OFF = 0x284
UNIT_POS_Y_OFF = 0x288

# 单位结构字段语义目录 (学自 trainer discovery_fields 的字段目标清单):
# 名字 -> (偏移, 说明)。经典引擎家族结构字段稳定 (1.24~1.28.5 同组,
# Still4 表 ItemsListOffset=0x1F8 与本地 1.27 实测互证); 属主/坐标
# 三字段在 1.27.0.52240 (KK) 真机验证。诊断失败时引用字段名而非整链。
UNIT_FIELD_LAYOUT: "dict[str, tuple[int, str]]" = {
    "owner_slot": (UNIT_OWNER_OFF, "属主玩家槽号/对象指针"),
    "pos_x": (UNIT_POS_X_OFF, "X 坐标 (float)"),
    "pos_y": (UNIT_POS_Y_OFF, "Y 坐标 (float)"),
    "type_code": (0x30, "类型四码 (fourcc, 大端)"),
    "inventory": (0x1F8, "背包列表指针 (Still4 表 ItemsListOffset 同值)"),
}


_FOURCC_RE = re.compile(r"[A-Za-z][0-9A-Za-z]{3}")

# 指针有效性: 整个用户态都是合法窗口, 拒绝的只有 NULL 和内核态。
# (旧写法把上限拍在 0x60000000, LAA/超大地图的高址对象被当垃圾整批丢弃。)
_HEAP_LO = 0x00010000
_HEAP_HI = 0x7FFE0000


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

# 偏移档案标识 (学自 trainer 的 PROFILE_ID 思路): 版本表/模板/诊断逻辑整体
# 升级时递增, journal 与 live notes 引用它, 坏读数可追溯到具体档案版。
# r2: 引入 per-build 档案层 (LiveBuildProfile/BUILD_PROFILES/resolve_profile),
# 覆盖 1.20~1.28 公开表 + 未收录 classic 模板档 + 重制版待建档。
LIVE_PROFILE_ID = "classic-chain-r2-multibuild"

# 单位链表 RVA (Still4/War3Trainer GameContext.cs 公开表, 1.20~1.28):
# 与资源链同源的第二锚, 供后续 UnitList 遍历类读取复用。
_UNIT_LIST_RVAS: dict[str, int] = {
    "1.20.4.6074": 0x8722BC,
    "1.21.0.6263": 0x873334,
    "1.21.1.6300": 0x873334,
    "1.22.0.6328": 0xAA2FFC,
    "1.23.0.6352": 0xABBE4C,
    "1.24.0.6372": 0xACD44C,
    "1.24.1.6374": 0xACD44C,
    "1.24.2.6378": 0xACD44C,
    "1.24.3.6384": 0xACD44C,
    "1.24.4.6387": 0xACD44C,
    "1.25.1.6397": 0xAB65F4,
    "1.26.0.6401": 0xAB65F4,
    "1.27.0.52240": 0xBE4238,
    "1.28.0.7205": 0xD730F0,
    "1.28.5.7680": 0xD305E0,
}


@dataclass(frozen=True, slots=True)
class ProfileFingerprint:
    """Game.dll PE 头三要素指纹 (学自 trainer GameProfile.fingerprint)。

    machine = PE Machine (0x14C x86 / 0x8664 x64), timestamp =
    TimeDateStamp, image_size = SizeOfImage。把档案锚定到具体二进制,
    防「版本号相同但 DLL 不同」的错配。
    """

    machine: int
    timestamp: int
    image_size: int


@dataclass(frozen=True, slots=True)
class ProfileCheck:
    """档案自校验项: Game.dll 的 rva 处期望内存字节 (学自 trainer _checks)。

    采样窗口已避开 .reloc 全部 HIGHLOW 目标, ASLR 下文件字节=内存字节。
    domain = 验证对象域 (schema 分域学自 trainer profiles JSON: resolver/
    game_state/context 各自一组); 经典档案全部在 text 域。
    """

    rva: int
    expect: bytes
    label: str = ""
    domain: str = "text"


@dataclass(frozen=True, slots=True)
class LiveBuildProfile:
    """一个游戏 build 的只读读取档案 (纯数据; 载入档案不载入可执行代码)。

    tier 档位: exact = 句柄链已真机验证; rva-table = 资源/单位链有公开表
    来源且句柄链可运行时推导; template = 未收录 classic 版本, 全部靠引擎
    家族结构推导; reforged-pending = 重制版 x64 档案待建立, 明确回退。
    fingerprint/checks = 运行时自验证 (可选): 指纹不符或校验字节不匹配
    时档案整体作废, 偏移不沿用。
    """

    version: str
    engine: str
    arch: str
    game_struct_rva: "int | None"
    unit_list_rva: "int | None"
    handle_chain: "LiveHandleOffsets | None"
    tier: str
    source: str
    fingerprint: "ProfileFingerprint | None" = None
    checks: "tuple[ProfileCheck, ...]" = ()
    # 档案格式版本 (学自 trainer schema_version; v1 = 经典链结构,
    # trainer 验证过的 v2 骨架 — 分域 checks/modules 开关/证据参考库
    # 分离 — 见 AGENTS.d/live.md, 重制版多 build 时启用)。
    schema_version: int = 1


# 1.27.0.52240 (KK) 的 PE 三要素与 .text 自校验样本 —— 从本机 Game.dll
# (13,187,048B, TimeDateStamp 0x56BD0E1C) 提取; 采样窗口解析并避开了
# .reloc 的 43.4 万个 HIGHLOW 目标, ASLR 下内存字节与文件字节一致。
# 换平台/换语言版 Game.dll 时这些校验会失败 -> 档案作废并回退推导,
# 这正是「不做静默错配」的设计意图。
_PROFILE_FINGERPRINTS: "dict[str, ProfileFingerprint]" = {
    "1.27.0.52240": ProfileFingerprint(
        machine=0x14C, timestamp=0x56BD0E1C, image_size=0xCD8000
    ),
}
_PROFILE_CHECKS: "dict[str, tuple[ProfileCheck, ...]]" = {
    "1.27.0.52240": (
        ProfileCheck(
            rva=0x2543A8,
            expect=b"\x6f\x8b\xc6\x5e\x5d\xc2\x04\x00\x55\x8b\xec\x56\xff\x75\x08\x8b",
            label="text-q1",
        ),
        ProfileCheck(
            rva=0x4A7740,
            expect=b"\x8b\x70\x54\x85\xf6\x74\x18\x8b\x06\x8b\xce\xff\x50\x1c\x8b\xd7",
            label="text-mid",
        ),
        ProfileCheck(
            rva=0x6FC1EC,
            expect=b"\xd4\xbe\x6f\x01\x00\x00\x00\xc3\xcc\xcc\xcc\xcc\xcc\xcc\xcc\xcc",
            label="text-q3",
        ),
    )
}

_build_profiles_cache: "dict[str, LiveBuildProfile] | None" = None


def build_profiles() -> "dict[str, LiveBuildProfile]":
    """惰性构建 per-build 档案表 (引用 HANDLE_CHAIN_OFFSETS/GAME_STRUCT_RVAS)。"""
    global _build_profiles_cache
    if _build_profiles_cache is None:
        table: dict[str, LiveBuildProfile] = {}
        for ver, rva in GAME_STRUCT_RVAS.items():
            chain = HANDLE_CHAIN_OFFSETS.get(ver)
            table[ver] = LiveBuildProfile(
                version=ver,
                engine="classic",
                arch="x86",
                game_struct_rva=rva,
                unit_list_rva=_UNIT_LIST_RVAS.get(ver),
                handle_chain=chain,
                tier="exact" if chain is not None else "rva-table",
                source=(
                    chain.source
                    if chain is not None
                    else "Still4/War3Trainer 公开表 (GameContext.cs); 句柄链待真机验证"
                ),
                fingerprint=_PROFILE_FINGERPRINTS.get(ver),
                checks=_PROFILE_CHECKS.get(ver, ()),
            )
        _build_profiles_cache = table
    return _build_profiles_cache


BUILD_PROFILES = build_profiles


def verify_profile(
    reader: "MemoryReader",
    dll_base: int,
    profile: LiveBuildProfile,
    dll_fingerprint: "ProfileFingerprint | None" = None,
) -> "tuple[bool, list[str], list[str]]":
    """档案运行时自验证 (学自 trainer: 加载即核对, 不做静默错配)。

    checks: 逐条在内存 Game.dll 的 RVA 读期望字节比对; 无 checks 的
    档案视为「无校验可做, 不拦截」。dll_fingerprint (来自磁盘 PE 头)
    提供时先比指纹三要素。返回 (是否通过, 失败描述列表, 运行时补丁差异列表)。

    归因规则: 磁盘 PE 三要素与档案一致 = 同一个文件, 内存字节不同只可能
    是平台加载后打的运行时补丁 (KK 类平台实证, 每局补的字节还可能不同),
    这种差异进 patches 交调用方写进 notes 作证据, 不拦截; 指纹不符 = 版本
    不明, text 差异硬拦截。
    """
    fails: list[str] = []
    patches: list[str] = []
    fp_matched = False
    if dll_fingerprint is not None and profile.fingerprint is not None:
        a, b = dll_fingerprint, profile.fingerprint
        if (
            a.machine != b.machine
            or a.timestamp != b.timestamp
            or a.image_size != b.image_size
        ):
            fails.append(
                "PE 指纹不符 (档案 %s/0x%X/0x%X vs 本机 %s/0x%X/0x%X)"
                % (
                    hex(b.machine),
                    b.timestamp,
                    b.image_size,
                    hex(a.machine),
                    a.timestamp,
                    a.image_size,
                )
            )
        else:
            fp_matched = True
    for c in profile.checks:
        got = reader.read(dll_base + c.rva, len(c.expect))
        if got != c.expect:
            entry = "[%s] %s@0x%X: 期望 %s, 实得 %s" % (
                c.domain,
                c.label or "check",
                c.rva,
                c.expect.hex(),
                got.hex() if got else "不可读",
            )
            if fp_matched:
                patches.append(entry)
            else:
                fails.append(entry)
    return (not fails), fails, patches


def resolve_profile(
    version: str | None, engine: str = "classic", arch: str = "x86"
) -> LiveBuildProfile:
    """档案解析三档: 精确命中 → 公开表 → 引擎家族模板 / 重制版待建。

    精确命中零额外开销直接返回; 未收录版本不沿用任何旧地址, 由
    derive_offsets (classic) 或调用方回退策略 (reforged) 现场解决。
    """
    v = str(version or "")
    hit = build_profiles().get(v)
    if hit is not None:
        return hit
    if engine == "reforged" or arch == "x64":
        return LiveBuildProfile(
            version=v,
            engine="reforged",
            arch="x64",
            game_struct_rva=None,
            unit_list_rva=None,
            handle_chain=None,
            tier="reforged-pending",
            source="重制版 x64 档案待建立 (需真机采集验证)",
        )
    return LiveBuildProfile(
        version=v,
        engine="classic",
        arch="x86",
        game_struct_rva=None,
        unit_list_rva=None,
        handle_chain=None,
        tier="template",
        source="未收录版本: classic 引擎家族结构推导 + 资源差分定位",
    )


def profile_to_dict(profile: LiveBuildProfile) -> dict[str, Any]:
    """档案 → JSON 兼容 dict (schema v1; 学自 trainer profiles/*.json)。

    bytes 以 hex 存; handle_chain 用 dataclasses.asdict 展开为纯标量。
    """
    d: dict[str, Any] = {
        "schema_version": profile.schema_version,
        "id": f"war3-classic-{profile.version}",
        "game_version": profile.version,
        "engine": profile.engine,
        "arch": profile.arch,
        "tier": profile.tier,
        "status": "validated" if profile.tier == "exact" else "unverified",
        "source": profile.source,
    }
    if profile.fingerprint is not None:
        fp = profile.fingerprint
        d["fingerprint"] = {
            "machine": fp.machine,
            "timestamp": fp.timestamp,
            "image_size": fp.image_size,
        }
    if profile.checks:
        d["checks"] = [
            {
                "rva": c.rva,
                "bytes": c.expect.hex(),
                "label": c.label,
                "domain": c.domain,
            }
            for c in profile.checks
        ]
    for name in ("game_struct_rva", "unit_list_rva"):
        v = getattr(profile, name)
        if v is not None:
            d[name] = v
    if profile.handle_chain is not None:
        d["handle_chain"] = asdict(profile.handle_chain)
    return d


def _strict_int(v: Any, label: str) -> int:
    """偏移类字段的严格 int: 拒绝浮点 (静默截断=静默错值) 与数字字符串。

    学自 trainer game_profile 形状校验 (Adapter value type differs):
    导入时拒绝, 不拖到使用时半路炸。
    """
    if isinstance(v, bool) or not isinstance(v, int):
        raise ValueError(f"档案字段 {label} 需要整数, 实得 {type(v).__name__}: {v!r}")
    return v


def profile_from_dict(d: dict[str, Any]) -> LiveBuildProfile:
    """JSON dict → 档案; schema 版本不符时明确拒绝 (不静默容错)。

    形状校验学自 trainer game_profile: 尺寸上限 / 逐字段类型严格化 /
    版本四段格式 — 导入时全部校验完, 坏档案在使用前被拒。
    """
    import re as _re

    v = int(d.get("schema_version", 1))
    if v != 1:
        raise ValueError(
            f"档案 schema v{v} 需要新版工具 (本工具支持 v1): {d.get('id', '?')}"
        )
    gv = str(d["game_version"])
    if not _re.fullmatch(r"\d+\.\d+\.\d+\.\d+", gv):
        raise ValueError(
            f"档案 game_version 需要四段数字版本号 (a.b.c.d), 实得: {gv!r}"
        )
    checks = tuple(
        ProfileCheck(
            rva=_strict_int(c["rva"], f"checks[{i}].rva"),
            expect=bytes.fromhex(str(c["bytes"])),
            label=str(c.get("label", "")),
            domain=str(c.get("domain", "text")),
        )
        for i, c in enumerate(d.get("checks", ()))
    )
    fp = d.get("fingerprint")
    hc_d = d.get("handle_chain")
    if hc_d:
        try:
            chain = LiveHandleOffsets(**hc_d)
        except TypeError as ex:
            raise ValueError(f"档案 handle_chain 字段与 schema 不符: {ex}") from ex
    else:
        chain = None
    if fp:
        try:
            fingerprint = ProfileFingerprint(**fp)
        except TypeError as ex:
            raise ValueError(f"档案 fingerprint 字段与 schema 不符: {ex}") from ex
        for k in ("machine", "timestamp", "image_size"):
            _strict_int(getattr(fingerprint, k), f"fingerprint.{k}")
    else:
        fingerprint = None
    return LiveBuildProfile(
        version=gv,
        engine=str(d.get("engine", "classic")),
        arch=str(d.get("arch", "x86")),
        game_struct_rva=d.get("game_struct_rva"),
        unit_list_rva=d.get("unit_list_rva"),
        handle_chain=chain,
        tier=str(d.get("tier", "exact")),
        source=str(d.get("source", "JSON 导入")),
        fingerprint=fingerprint,
        checks=checks,
        schema_version=v,
    )


def describe_live_profile(
    version: str | None, engine: str = "classic", arch: str = "x86"
) -> str:
    """一行诊断: 当前游戏版本命中的档案档位。

    四档: 已验证句柄链 (exact) / 公开表收录 (rva-table) / 未收录 classic
    模板 (template) / 重制版待建 (reforged-pending)。live 报告 notes 必须
    携带本行, 非精确档位上的归属断言据此降级。
    """
    p = resolve_profile(version, engine, arch)
    if p.tier == "exact":
        return f"偏移档案: {p.version} 已验证 ({p.source}; {LIVE_PROFILE_ID})"
    if p.tier == "rva-table":
        return (
            f"偏移档案: {p.version} 资源链/单位链已收录 (公开表),"
            f" 句柄链运行时按 classic 模板推导 ({LIVE_PROFILE_ID})"
        )
    if p.tier == "reforged-pending":
        return (
            f"偏移档案: {p.version} 重制版 x64: 句柄链/资源链档案待建立,"
            f" 回退 chain/icons 策略 ({LIVE_PROFILE_ID})"
        )
    return (
        f"偏移档案: {p.version} 未收录 (classic 家族), 结构推导与资源差分"
        f" 尽力而为; 已验证仅 1.27.0.52240 ({LIVE_PROFILE_ID})"
    )


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
        from .memory_regions import contiguous_regions

        pairs = [(int(base), bytes(data)) for base, data in regions if data]
        pairs.sort()
        self._data = dict(contiguous_regions(pairs))
        self._bases = sorted(self._data)

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


def reader_from_snapshot(result) -> "MemoryReader":
    """把 live_inventory.snapshot() 的 (regions, total) 返回值安全转成 MemoryReader。

    直接把该二元组传给 MemoryReader 会把 (区域列表, 总字节) 当作两个区域迭代,
    真实进程中以 "too many values to unpack" 崩溃; 这里显式解包固定形态。
    """
    regions, _total = result
    return MemoryReader(regions)


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
            _HEAP_LO <= t.base < _HEAP_HI and 0 < t.bound <= (_HEAP_HI - t.base) // 8
            for t in self.tables
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

    def live_objects(self):
        """枚举句柄表中所有存活对象地址 (单位/物品/UI 混在一起)。

        无上限: 句柄表自身的 bound 就是完备边界, 走满为止。
        """
        o = self._o
        r = self._r
        found: list[int] = []
        for table in self.tables:
            if not table.base:
                continue
            for index in range(table.bound):
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
) -> list[UnitInventory]:
    """全对象扫描, 返回带有效物品四码的单位 (英雄/宝宝/商店怪)。无上限。"""
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
    units.sort(key=lambda u: -len(u.items))
    return units


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
    # Coordinates are float32 fields. Reject non-finite values while retaining
    # every finite off-map coordinate as evidence from the actual structure.
    if not math.isfinite(x) or not math.isfinite(y):
        return (0.0, 0.0)
    return (x, y)


def walk_owned_units(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
) -> list[OwnedUnit]:
    """全对象扫描, 返回所有带合法四码且所有者可读的单位 (含地图物件)。无上限。"""
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
    return units


def summarize_owners(units: list[OwnedUnit]) -> tuple[dict[int, int], list[OwnedUnit]]:
    """按所有者汇总: (每个玩家号的数量, 全部单位按槽位排序)。

    不做大小槽位分类: 旧 list_cap=8 会把挂了上千生成物件的真人槽位整槽
    隐掉再靠打捞补录, 现在直接全量列出, 物件多就多打印几行。
    """
    counts: dict[int, int] = {}
    for u in units:
        counts[u.owner] = counts.get(u.owner, 0) + 1
    listed = sorted(units, key=lambda u: (u.owner, u.code, round(u.x), round(u.y)))
    return counts, listed


@dataclass(frozen=True, slots=True)
class PlayerResources:
    """一个玩家资源结构: 结构地址 + 金币/木材 (+人口尽力识别)。"""

    addr: int
    gold: float | None
    lumber: float | None = None
    food: int | None = None
    food_cap: int | None = None


# 权威资源链 (来源: Still4/War3Trainer GameContext/GameTrainer, 1.20~1.28 全版本表;
# 1.27.0.52240 在 KK 经典平台实测验证)。金/木内部为 x10 整数 (9639 = 963.9 金)。
GAME_STRUCT_RVAS: dict[str, int] = {
    "1.20.4.6074": 0x87C744,
    "1.21.0.6263": 0x87D7BC,
    "1.21.1.6300": 0x87D7BC,
    "1.22.0.6328": 0xAA4178,
    "1.23.0.6352": 0xABCFC8,
    "1.24.0.6372": 0xACE5E0,
    "1.24.1.6374": 0xACE5E0,
    "1.24.2.6378": 0xACE5E0,
    "1.24.3.6384": 0xACE5E0,
    "1.24.4.6387": 0xACE5E0,
    "1.25.1.6397": 0xAB7788,
    "1.26.0.6401": 0xAB7788,
    "1.27.0.52240": 0xBE40A8,
    "1.28.0.7205": 0xD72F58,
    "1.28.5.7680": 0xD30448,
}

# 12 个玩家资源块相对 (游戏内存基址 & 0xFFFF0000) 的偏移。
PLAYER_RESOURCE_BASES = (
    0x190,
    0x1410,
    0x26A0,
    0x3920,
    0x4BB0,
    0x5E30,
    0x70C0,
    0x8350,
    0x95D0,
    0xA860,
    0xBAE0,
    0xCD70,
)


def _to_signed(x):
    if x is None:
        return None
    return x - 0x100000000 if x >= 0x80000000 else x


def read_player_resources_chain(read_u32, dll_base: int, version: str):
    """权威指针链直读全队资源 (免扫描免报数)。

    read_u32: 回调 (地址)->int|None (ReadProcessMemory 或快照读取)。
    返回 PlayerResources 列表 (P1..P12, 金/木为内部值/10, 人口尽力)。
    """
    rva = GAME_STRUCT_RVAS.get(str(version or ""))
    if not rva or not dll_base:
        return None
    this_game = read_u32(dll_base + rva)
    if not this_game:
        return None
    game_mem = read_u32(this_game + 0xC)
    if not game_mem or game_mem == 0xFFFFFFFF:
        return None
    raw = read_u32(game_mem + 0xC)
    if not raw:
        return None
    upper = raw & 0xFFFF0000
    rows: list[PlayerResources] = []
    for base in PLAYER_RESOURCE_BASES:
        gold_i = _to_signed(read_u32(upper + base))
        lumber_i = _to_signed(read_u32(upper + base + 0x80))
        food_i = _to_signed(read_u32(upper + base + 0x200))
        cap_i = _to_signed(read_u32(upper + base + 0x180))
        gold = gold_i / 10 if gold_i and 0 < gold_i < 40_000_000 else None
        lumber = lumber_i / 10 if lumber_i and 0 < lumber_i < 40_000_000 else None
        food = food_i if food_i is not None and 0 <= food_i < 300 else None
        rows.append(PlayerResources(upper + base, gold, lumber, food, cap_i))
    return rows


def _plausible_resource(f: float) -> bool:
    """资源值特征: 有限、非负、常规数量级 (允许小数, 收入按秒累加)。"""
    return math.isfinite(f) and 0 <= f < 10_000_000


def _matches_reported(f: float, reported: float) -> bool:
    """HUD 显示的是取整值; 内部 float 带小数, 用 +/-1 容差匹配。"""
    return abs(f - reported) <= 1.0


# 资源锚缓存 (学自 trainer ResourceCacher 的"地址缓存+签名复验"思路):
# 报数校准找到的 (金币地址, 木地址相对偏移) 组。复探先按缓存地址读值,
# 全部通过 ±1 容差校验才免全扫; 任一失效自动回全扫。引擎堆会搬移小型
# 结构, 因此缓存只做加速永远不做事实——值校验不过就以全扫为准。
_resource_anchors: "list[tuple[int, int]] | None" = None
_resource_cache_hit = False


def cached_resource_hit() -> bool:
    """上次 find_resource_layout 是否命中了锚缓存 (供报告 notes 引用)。"""
    return _resource_cache_hit


def _probe_food(reader: "MemoryReader", gold_addr: int, delta: int) -> "int | None":
    """尽力识别人口: 常见相对偏移处第一个数量级合理的 float。"""
    for fo in (delta + 4, delta + 8, delta - 4, 4, 8):
        raw = reader.read(gold_addr + fo, 4)
        if not raw:
            continue
        fv = struct.unpack("<f", raw)[0]
        if _plausible_resource(fv) and round(fv) <= 1000:
            return round(fv)
    return None


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
    reader: "MemoryReader",
    gold: float,
    lumber: float,
    window: int = 0x100,
    use_cache: bool = True,
) -> list[PlayerResources]:
    """以当前已知的一组 金币/木材 数值为锚, 定位同布局的玩家资源结构列表。

    原理: HUD 显示值为取整, 内部为带小数的 float (收入按秒累加), 因此用
    +/-1 容差匹配; 在 +/- window 内找木材 float; 同一 (金币->木材) 相对
    偏移的其余结构即为其他玩家/缓存副本。引擎为每个玩家维护同构资源结构,
    布局一致而地址不同。注意: 小型资源结构可能被引擎堆管理器搬移, 校准
    应在报数后数秒内执行。

    锚缓存: 上次校准的 (金币地址, 木偏移) 组先按本次报数做 ±1 值复验,
    全部通过才免全扫 (cached_resource_hit() 返回 True); 任一失效自动回
    全扫并重填缓存。换局/搬移天然失效, 不会返回过期地址。
    """
    global _resource_anchors, _resource_cache_hit
    if use_cache and _resource_anchors:
        replay: list[PlayerResources] = []
        ok = True
        for g_addr, delta in _resource_anchors:
            gr = reader.read(g_addr, 4)
            lr = reader.read(g_addr + delta, 4)
            if not gr or not lr:
                ok = False
                break
            gv = struct.unpack("<f", gr)[0]
            lv = struct.unpack("<f", lr)[0]
            if not (
                _plausible_resource(gv)
                and _plausible_resource(lv)
                and _matches_reported(gv, gold)
                and _matches_reported(lv, lumber)
            ):
                ok = False
                break
            replay.append(
                PlayerResources(g_addr, gv, lv, _probe_food(reader, g_addr, delta))
            )
        if ok:
            _resource_cache_hit = True
            return replay
    _resource_cache_hit = False
    gold_addr = []
    lumber_addr = []
    for addr, f in _iter_float_slots(reader):
        if _matches_reported(f, gold):
            gold_addr.append(addr)
        elif _matches_reported(f, lumber):
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
        lum_addr = g + best_delta
        gold_raw = reader.read(g, 4)
        lumber_raw = reader.read(lum_addr, 4)
        if not gold_raw or not lumber_raw:
            continue
        gold_val = struct.unpack("<f", gold_raw)[0]
        lumber_val = struct.unpack("<f", lumber_raw)[0]
        out.append(
            PlayerResources(g, gold_val, lumber_val, _probe_food(reader, g, best_delta))
        )
    _resource_anchors = [(g, best_delta) for g in anchors] if out else None
    return out


def find_auto_resource_rows(
    readers: "list[MemoryReader]",
    min_gold: float = 100.0,
) -> list[PlayerResources]:
    """自动差分定位: 多个快照中"单调上涨"的 float 即为打钱玩家的金币。

    免报数校准: 打怪/经营时金币只涨不跌且带小数 (坐标/血量会回落或整跳),
    连拍 3 个快照取一路上涨者为金币锚; 木头取 +0x4、人口取 +0x8/+0xC 的
    尽力识别 (结构为引擎 UI 缓存, 会被堆搬移, 必须同进程内完成发现+读取)。
    """
    if len(readers) < 2:
        return []

    def collect(reader: "MemoryReader") -> dict[int, float]:
        out: dict[int, float] = {}
        for base_a, data in reader._data.items():
            if len(data) < 0x100:
                continue
            for off in range(0, len(data) - 4, 4):
                f = struct.unpack_from("<f", data, off)[0]
                if math.isfinite(f) and min_gold <= f <= 100000:
                    out[base_a + off] = f
        return out

    series = [collect(r) for r in readers]
    last = series[-1]
    rows: list[PlayerResources] = []
    for addr, v_final in last.items():
        values: list[float] = []
        for s in series:
            v = s.get(addr)
            if v is None:
                values = []
                break
            values.append(v)
        if len(values) != len(series):
            continue
        if not all(values[i] < values[i + 1] for i in range(len(values) - 1)):
            continue
        if not 0.3 < v_final - values[0] < 2000:
            continue
        blk = readers[-1].read(addr, 0x10)
        if not blk:
            continue
        lumber = None
        lumber_f = struct.unpack_from("<f", blk, 4)[0]
        if _plausible_resource(lumber_f) and lumber_f <= 100000:
            lumber = lumber_f
        food = None
        for fo in (8, 12):
            fv = struct.unpack_from("<f", blk, fo)[0]
            if _plausible_resource(fv) and round(fv) <= 100:
                food = round(fv)
                break
        rows.append(PlayerResources(addr, v_final, lumber, food))
    rows.sort(key=lambda r: r.addr)
    return rows


def rank_auto_rows(rows: list[PlayerResources]) -> tuple[list[PlayerResources], int]:
    """auto 锚点可信度排序, 全量输出 (满量纪律: 不设封顶)。

    差分定位会把所有一路上涨的 float 都当金币锚 (成长计数器/波次计时等),
    动态图一局能到数千个; 真正的玩家行木/人口同时可读, 排前面,
    其余按地址稳定排序。返回 (全部排序行, 总数)。
    """
    total = len(rows)
    ranked = sorted(rows, key=lambda r: (r.lumber is None, r.food is None, r.addr))
    return ranked, total


def read_local_player_index(
    reader: MemoryReader, dll_base: int, o: LiveHandleOffsets
) -> int | None:
    """本地玩家槽位号 (0 起始内存槽; 大厅显示 = 槽位+1)。读不到返回 None。"""
    vmctx = reader.u32(dll_base + o.vmctx_global_rva)
    if not vmctx:
        return None
    raw = reader.read(vmctx + o.player_idx_off, 2)
    if not raw:
        return None
    return struct.unpack("<H", raw)[0]


def owner_slot_codes(units: list[OwnedUnit]) -> dict[int, dict[str, int]]:
    """按玩家槽位汇总单位四码计数: {槽位: {四码: 数量}}。

    输入用 walk_owned_units 的全量结果, 不做二次扫描。
    """
    out: dict[int, dict[str, int]] = {}
    for u in units:
        codes = out.setdefault(u.owner, {})
        codes[u.code] = codes.get(u.code, 0) + 1
    return out


def parse_nick_overrides(raw):
    """--nick "1=名字A,2=名字B" (大厅玩家号) -> {0起始槽位: 名字}。

    引擎侧不保存平台玩家名 (KK 只在聊天/事件缓冲留 Unicode 副本, 不绑定
    槽位), 真名由调用者按大厅号指定一次; 解析容错: 逗号分隔, 忽略坏段。
    """
    if not raw:
        return {}
    out: dict[int, str] = {}
    for raw_part in str(raw).split(","):
        part = raw_part.strip()
        if not part or "=" not in part:
            continue
        num, _, name = part.partition("=")
        num, name = num.strip(), name.strip()
        if num.isdigit() and 1 <= int(num) <= 12 and name:
            out[int(num) - 1] = name
    return out


def format_player_rows(
    rows: list[PlayerResources],
    slot_codes: dict[int, dict[str, int]],
    unit_names: dict[bytes, str],
    local_index: int | None,
    nicks: dict[int, str] | None = None,
) -> list[str]:
    """把权威链的按槽资源行格式化为 '玩家N(名字): 金X 木Y 人口Z  <-- 你'。

    槽位为 0 起始内存槽, 显示号 = 槽位+1 (大厅玩家号);
    名字优先取 nicks (--nick 指定的真实玩家名, 大厅号-1 为键),
    否则取该槽位英雄型四码 (O/E/H/U + 数字) 中英雄型四码按数量降序全部用 · 连接,
    金币为空且无英雄的空槽位跳过。名字查不到时回退四码。
    """
    lines: list[str] = []
    for i, r in enumerate(rows):  # 全部非空槽位 (旧 [:12] 曾静默丢裁判槽)
        codes = slot_codes.get(i) or {}
        heroes = [
            c for c in codes if len(c) == 4 and c[0] in "OEHU" and c[1:].isdigit()
        ]
        heroes.sort(key=lambda c: -codes[c])
        hero_names = [
            unit_names.get(c.encode("latin-1"), c) for c in heroes
        ]  # 全部英雄型四码
        label = (nicks or {}).get(i) or (
            "·".join(hero_names) if hero_names else "无英雄"
        )
        gold = f"{r.gold:.0f}" if r.gold is not None else "-"
        lumber = f"{r.lumber:.0f}" if r.lumber is not None else "-"
        food = f"{r.food}" if r.food is not None else "-"
        if r.gold is None and not heroes:
            continue  # 空槽位
        mark = "  <-- 你" if local_index == i else ""
        lines.append(f"玩家{i + 1}({label}): 金{gold} 木{lumber} 人口{food}{mark}")
    return lines


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
        if not (_HEAP_LO <= base < _HEAP_HI) or not (
            0 < bound <= (_HEAP_HI - base) // 8
        ):
            return False
        for region_base, data in reader.iter_regions():
            start = max(0, (region_base - base + 7) // 8)
            end = min(bound, (region_base + len(data) - base) // 8)
            for index in range(start, end):
                marker, wrapper = struct.unpack_from(
                    "<II", data, base + index * 8 - region_base
                )
                if marker != 0xFFFFFFFE or not (_HEAP_LO <= wrapper < _HEAP_HI):
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


class ScanBudget:
    """发现过程的有界预算 (学自 trainer ScanBudget): 时间截止 + 取消。

    超限不是失败而是「未完成」——推导全程只读不写游戏, 重试安全。
    调用方据此把「结构推导失败」和「预算耗尽可稍后重试」分开报告。
    """

    def __init__(self, deadline_s: float = 0.0, cancelled: bool = False):
        self._start = time.monotonic()
        self.deadline_s = float(deadline_s)
        self.cancelled = bool(cancelled)
        self.timed_out = False

    def check(self) -> bool:
        """是否允许继续; 超限时置位 timed_out 并返回 False。"""
        if self.cancelled:
            return False
        if self.deadline_s > 0 and time.monotonic() - self._start > self.deadline_s:
            self.timed_out = True
            return False
        return True


@dataclass(frozen=True, slots=True)
class DiscoveryStage:
    """发现流水线的阶段 (学自 trainer: 每阶段一条进度文案)。

    name 是机器名 (日志/诊断字段), message 是中文进度文案
    (报告 notes/UI 用)。失败时报告「最后到达阶段」, 诊断粒度
    从「推导失败」细化到「死在哪一步」。
    """

    name: str
    message: str


DERIVE_STAGES: "dict[str, DiscoveryStage]" = {
    "candidates": DiscoveryStage("candidates", "正在收集句柄管理器候选"),
    "build-systems": DiscoveryStage("build-systems", "正在构建句柄系统并做结构校验"),
    "strict-verify": DiscoveryStage(
        "strict-verify", "正在严格校验选中链 (要求玩家号合法+选中带背包)"
    ),
    "loose-verify": DiscoveryStage("loose-verify", "正在放宽校验选中链 (类型四码即可)"),
    "complete": DiscoveryStage("complete", "自动定位完毕, 偏移按已确认数据使用"),
}


def derive_offsets(
    reader: MemoryReader,
    dll_base: int,
    dll_end: int,
    scan_limit: int = 0,
    max_hm_candidates: int = 0,
    budget: "ScanBudget | None" = None,
    on_stage: "Callable[[DiscoveryStage], None] | None" = None,
) -> LiveHandleOffsets | None:
    """在 Game.dll 内存中按结构特征自动识别两个全局槽, 生成偏移表。

    不依赖版本号或硬编码 RVA: 先收集"长得像句柄管理器"的候选,
    逐个构建句柄系统并用选中链端到端验证, 全部通过才算成功
    (避免先遇到的假阳性候选导致整体失败)。
    scan_limit<=0 (默认) 扫完整 DLL 段; max_hm_candidates<=0 (默认) 候选满量收集,
    不设人为截断 — 时间安全由 ScanBudget 时间闸兜底。
    适用于经典引擎家族; 失败/预算耗尽返回 None (调用方用
    budget.timed_out 区分「推导失败」与「可稍后重试」)。
    on_stage: 每进入一个阶段回调一次 (顺序见 DERIVE_STAGES;
    loose-verify 仅在严格校验全军覆没后出现)。
    """

    def _enter(name: str) -> None:
        if on_stage is not None:
            on_stage(DERIVE_STAGES[name])

    # scan_limit<=0 = 扫完整 DLL 段 (旧 64MB 默认曾截掉大体积 Game.dll 的后段候选)
    hi = min(dll_end, dll_base + scan_limit) if scan_limit > 0 else dll_end
    if hi <= dll_base:
        return None
    tpl = classic_template()
    _enter("candidates")
    hm_candidates: list[tuple[int, int]] = []
    seen_managers: set[int] = set()
    for _tick, (addr, value) in enumerate(_iter_dwords(reader, dll_base, hi), start=1):
        if not _tick & 0xFFFF and budget is not None and not budget.check():
            return None
        if (
            _HEAP_LO <= value < _HEAP_HI
            and value not in seen_managers
            and _looks_like_handle_manager(reader, value, tpl)
        ):
            seen_managers.add(value)
            hm_candidates.append((addr, value))
            if 0 < max_hm_candidates <= len(hm_candidates):
                break
    _enter("build-systems")
    systems: list[tuple[LiveHandleOffsets, HandleSystem]] = []
    for hm_slot, _hm in hm_candidates:
        stage = replace(tpl, handle_mgr_global_rva=hm_slot - dll_base)
        system = HandleSystem(reader, dll_base, stage)
        if system.valid:
            systems.append((stage, system))
    # 先全员严格校验 (要求玩家号合法 + 选中单位带背包), 再放宽到四码即可。
    # 同一轮校验的多个候选 system 共享一次全量遍历 (学自 trainer
    # scan_bytes_many 多模式单轮思想): N 个候选从 2N 次遍历降到 2 次。
    # 顺序语义: 以地址序返回首个通过端到端验证的 (system, vmctx) 组合;
    # 多解同时通过时任意一组都是功能正确的读取配置。
    _enter("strict-verify")
    # 严格轮不提前返回: 收集全部通过候选后取地址序首个, 多解时把歧义
    # 标注进 source (学 trainer discovery_validation 三态 confirmed/
    # ambiguous/unresolved — 歧义可见而非静默选择; 推导是一次性成本,
    # 固化后走档案不再推导)。
    strict_hits: list[tuple[int, "LiveHandleOffsets"]] = []
    _tick = 0
    for addr, value in _iter_dwords(reader, dll_base, hi):
        _tick += 1
        if not _tick & 0xFFFF and budget is not None and not budget.check():
            return None
        if not (_HEAP_LO <= value < _HEAP_HI):
            continue
        for stage, system in systems:
            if _selection_chain_valid(reader, system, tpl, value, True):
                strict_hits.append((addr, stage))
    if strict_hits:
        addr, stage = strict_hits[0]
        result = replace(
            stage,
            vmctx_global_rva=addr - dll_base,
            source=(
                "结构特征自动推导 (classic 模板)"
                + (
                    f" [多解歧义: {len(strict_hits)} 个候选通过严格校验, 取地址序首个]"
                    if len(strict_hits) > 1
                    else ""
                )
            ),
        )
        _enter("complete")
        return result
    for require_inventory in (False,):
        _enter("loose-verify")
        _tick = 0
        for addr, value in _iter_dwords(reader, dll_base, hi):
            _tick += 1
            if not _tick & 0xFFFF and budget is not None and not budget.check():
                return None
            if not (_HEAP_LO <= value < _HEAP_HI):
                continue
            for stage, system in systems:
                if _selection_chain_valid(
                    reader, system, tpl, value, require_inventory
                ):
                    result = replace(
                        stage,
                        vmctx_global_rva=addr - dll_base,
                        source="结构特征自动推导 (classic 模板, 宽松校验)",
                    )
                    _enter("complete")
                    return result
    return None


def selected_unit(
    reader: MemoryReader,
    system: HandleSystem,
    o: LiveHandleOffsets,
    dll_base: int,
    max_walk: int | None = None,
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
    seen: set[int] = set()
    while entry not in seen and (max_walk is None or len(seen) < max_walk):
        if not (_HEAP_LO <= entry < _HEAP_HI):
            break
        seen.add(entry)
        lo = reader.u32(entry + o.entry_pair_off)
        hi = reader.u32(entry + o.entry_pair_off + 4)
        unit = system.resolve(lo, hi)
        if unit is not None:
            inv = read_inventory(reader, system, o, unit)
            if inv.code:
                return inv
        entry = reader.u32(entry)
    return None
