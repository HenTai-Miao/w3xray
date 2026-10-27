"""预放置实例解析：war3map.doo（装饰物/可破坏物）、war3mapUnits.doo（单位）。

魔兽的"对象定义"（w3u/w3t/…，由 w3obj.py 解析）只说有哪些单位/物品；
.doo 才说这些东西"摆在地图哪、属于哪个玩家、初始多少血/金"。这是定义之外的另一维信息。

格式来源：
- 装饰物 doo：移植自 w3x2lni frontend_doo.lua；单位 doo（TFT 版本 8）按真实地图逐字节验证。
- **经典 vs 重制版**：两者同为 version 8/sub 11，但重制版每条记录在 scale 后多一个 4 字节皮肤码，
  无法靠版本号区分。故两种布局都试，并校验单位 EOF / 装饰物特殊物尾表（数据自适应）。已用真实
  重制版地图（27 张 Season1 对战图 + Darkborne RPG 33944 装饰物）逐字节验证（解析到 EOF）。
不可信文件：单条记录损坏/老格式变长尾部对不上时，保留已成功解析的实例后停止，
绝不抛、不死循环（与 w3obj.py 的逐对象容错一致）。
"""

from __future__ import annotations

import math
import struct
import sys
from dataclasses import dataclass

from .doo_drops import flatten_drop_sets, read_count, read_drop_sets
from .doo_models import Doodad, Unit


_DOODAD_MIN_SIZE = 50  # 空掉落表，含 serial；重制版另加 4 字节 skin。
_UNIT_MIN_SIZE = 107  # TFT：空掉落/背包/技能，randomFlag=-1。
_ROC_UNIT_MIN_SIZE = 87  # RoC：比 TFT 少英雄三围和颜色/传送门。
_SPECIAL_DOODAD_SIZE = 16


@dataclass(frozen=True, slots=True)
class PlacementParseReport[PlacementT]:
    """Recovered placements plus the source's structural completeness issues."""

    records: tuple[PlacementT, ...]
    issues: tuple[str, ...] = ()


def _header_issues(data: bytes) -> tuple[str, ...]:
    version, subversion = struct.unpack_from("<ii", data, 4)
    if (version, subversion) not in {(7, 9), (8, 11)}:
        return (f"unsupported placement version: {version}/{subversion}",)
    return ()


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    @property
    def remaining(self) -> int:
        return len(self.d) - self.p

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def u8(self) -> int:
        if self.p >= len(self.d):
            raise IndexError("u8 越界")
        v = self.d[self.p]
        self.p += 1
        return v

    def tag(self) -> str:
        if self.p + 4 > len(self.d):
            raise IndexError("tag 越界")
        b = self.d[self.p : self.p + 4]
        self.p += 4
        return b.decode("latin-1")


def _read_doodad(r: _Reader, skin: bool) -> Doodad:
    """读一条装饰物记录。skin=True 时在 scale 后多读 4 字节皮肤码（重制版）。

    掉落数须能装进剩余字节并留下 serial；越界抛 ValueError，供上层换布局重试。
    """
    if r.remaining < _DOODAD_MIN_SIZE + (4 if skin else 0):
        raise ValueError("装饰物记录截断")
    record_offset = r.p
    tid = r.tag()
    var = r.i32()
    x, y, z = r.f32(), r.f32(), r.f32()
    angle = math.degrees(r.f32())
    scale = (r.f32(), r.f32(), r.f32())
    if skin:
        r.tag()  # 重制版皮肤码 4 字节
    vis = r.u8()
    life = r.u8()
    r.i32()  # 掉落列表指针
    # 掉落表是嵌套的：先 集合数，每个集合内再列若干 (物品码, 概率)。
    # 旧实现把它当成扁平的物品列表，遇到任何带掉落的装饰物就会错位 4 字节并连锁解崩
    # （真实地图里多数装饰物无掉落，故 bug 常被掩盖，直到某条带掉落才暴露）。
    drop_sets = read_drop_sets(r, tail_bytes=4)
    drops = flatten_drop_sets(drop_sets)
    serial = r.i32()
    return Doodad(
        type_id=tid,
        variation=var,
        x=x,
        y=y,
        z=z,
        angle=angle,
        scale=scale,
        flags=vis,
        life=life,
        drops=drops,
        serial=serial,
        drop_sets=drop_sets,
        source_offset=record_offset,
    )


def _attempt_doodads(data: bytes, count: int, skin: bool) -> tuple[list[Doodad], bool]:
    """解析主表；只有特殊物尾表也恰好吻合才确认该布局完整。"""
    r = _Reader(data)
    r.p = 16  # 跳过 magic+version+sub+count
    result: list[Doodad] = []
    for _ in range(count):
        try:
            result.append(_read_doodad(r, skin))
        except struct.error, IndexError, ValueError:
            return result, False
    return result, _valid_doodad_tail(r)


def _valid_doodad_tail(r: _Reader) -> bool:
    """The ignored special-doodad table still proves the main layout's boundary."""
    if r.remaining < 8:
        return False
    version = r.i32()
    count = r.i32()
    return version == 0 and count >= 0 and r.remaining == count * _SPECIAL_DOODAD_SIZE


def parse_doodads(data: bytes) -> list[Doodad]:
    """解析 war3map.doo，返回 Doodad 列表（仅装饰物主表，忽略特殊物）。

    经典与重制版同为 version 8/sub 11，但重制版每条多一个 4 字节皮肤码，无法靠版本区分。
    故两种布局都试，主表与特殊物尾表均吻合才确认布局；都不完整则返回读得更多的部分。
    """
    report = parse_doodads_report(data)
    if report.issues:
        print("[doo] war3map.doo: " + "; ".join(report.issues), file=sys.stderr)
    return list(report.records)


def parse_doodads_report(data: bytes) -> PlacementParseReport[Doodad]:
    """Retain partial main-table records without losing special-tail diagnostics."""
    if len(data) < 16 or data[:4] != b"W3do":
        return PlacementParseReport((), ("invalid placement header",))
    count = struct.unpack_from("<i", data, 12)[0]
    if count < 0:
        return PlacementParseReport((), (f"invalid placement count: {count}",))
    issues = _header_issues(data)
    # 不预拒绝截断文件的主表 count：逐条最低长度检查会按字节终止，保留已读实例。
    best: list[Doodad] = []
    for skin in (False, True):  # 先经典后重制
        result, full = _attempt_doodads(data, count, skin)
        if full:
            return PlacementParseReport(tuple(result), issues)
        if len(result) > len(best):
            best = result
    return PlacementParseReport(
        tuple(best),
        (
            *issues,
            f"recovered {len(best)} of {count} placements; no complete classic/reforged "
            "layout (main table or special-doodad tail is invalid/truncated "
            "or has trailing bytes)",
        ),
    )


def _read_unit(r: _Reader, skin: bool, v7: bool = False) -> Unit:
    """读一条单位记录。skin=True 时 scale 后多读 4 字节皮肤码（重制版）。

    v7=True 为经典 RoC（war3mapUnits.doo 版本 7）布局：相比 TFT(版本 8) 少了
    英雄 力量/敏捷/智力 三个字段，以及尾部的 自定义颜色 / 传送门 两个字段（皆 TFT 新增）。
    各 count 按剩余字节/记录最小长度/必要尾部校验，越界抛 ValueError 以换布局重试。
    """
    minimum_size = (_ROC_UNIT_MIN_SIZE if v7 else _UNIT_MIN_SIZE) + (4 if skin else 0)
    if r.remaining < minimum_size:
        raise ValueError("单位记录截断")
    record_tail = 4 if v7 else 12  # serial，及 TFT 的颜色/传送门。
    record_offset = r.p
    tid = r.tag()
    var = r.i32()
    x, y, z = r.f32(), r.f32(), r.f32()
    angle = math.degrees(r.f32())
    r.f32()  # scale x
    r.f32()  # scale y
    r.f32()  # scale z
    if skin:
        r.tag()  # 重制版皮肤码 4 字节
    r.u8()  # flags
    player = r.i32()
    r.u8()  # unknown
    r.u8()  # unknown
    hp = r.i32()
    mana = r.i32()
    r.i32()  # dropped-item-set 指针
    # 金币/获取范围/英雄等级、三种 count/flag、版本相关字段都不能被掉落表借用。
    drop_sets = read_drop_sets(r, tail_bytes=record_tail + 24 + (0 if v7 else 12))
    gold = r.i32()
    r.f32()  # 目标获取范围
    hlev = r.i32()
    if not v7:
        r.i32()  # 英雄力量（仅 TFT 版本 8）
        r.i32()  # 英雄敏捷（仅 TFT 版本 8）
        r.i32()  # 英雄智力（仅 TFT 版本 8）
    nitems = read_count(r, "背包物品数", 8, tail_bytes=record_tail + 8)
    items: list[tuple[int, str]] = []
    for _ in range(nitems):
        slot = r.i32()
        items.append((slot, r.tag()))
    nab = read_count(r, "技能数", 12, tail_bytes=record_tail + 4)
    abilities: list[tuple[str, int, int]] = []
    for _ in range(nab):
        aid = r.tag()
        active = r.i32()
        level = r.i32()
        abilities.append((aid, active, level))
    rflag = r.i32()
    if rflag == -1:
        pass  # 固定单位：无附加随机选择数据
    elif rflag == 0:
        r.i32()
    elif rflag == 1:
        r.i32()
        r.i32()
    elif rflag == 2:
        n = read_count(r, "随机组数", 8, tail_bytes=record_tail)
        for _ in range(n):
            r.tag()
            r.i32()
    else:
        raise ValueError("未知 randomFlag %d" % rflag)
    if not v7:
        r.i32()  # 自定义颜色（仅 TFT 版本 8）
        r.i32()  # 传送门（仅 TFT 版本 8）
    serial = r.i32()
    return Unit(
        type_id=tid,
        variation=var,
        x=x,
        y=y,
        z=z,
        angle=angle,
        player=player,
        hp=hp,
        mana=mana,
        gold=gold,
        hero_level=hlev,
        items=items,
        abilities=abilities,
        serial=serial,
        drop_sets=drop_sets,
        source_offset=record_offset,
    )


def _attempt_units(
    data: bytes, count: int, skin: bool, v7: bool = False
) -> tuple[list[Unit], bool]:
    """按皮肤/版本解析；只有全部记录恰好到 EOF 才确认该布局完整。"""
    r = _Reader(data)
    r.p = 16  # 跳过 magic+version+sub+count
    result: list[Unit] = []
    for _ in range(count):
        try:
            result.append(_read_unit(r, skin, v7))
        except struct.error, IndexError, ValueError:
            return result, False
    return result, r.remaining == 0


def parse_units(data: bytes) -> list[Unit]:
    """解析 war3mapUnits.doo，返回 Unit 列表。

    经典与重制版同为 version 8/sub 11，但重制版每条多一个 4 字节皮肤码（无法靠版本区分）。
    两种布局都试，取完整读完所有 count 且恰到 EOF 的那个；否则保留读得更多的部分并告警。
    """
    report = parse_units_report(data)
    if report.issues:
        print("[doo] war3mapUnits.doo: " + "; ".join(report.issues), file=sys.stderr)
    return list(report.records)


def parse_units_report(data: bytes) -> PlacementParseReport[Unit]:
    """Retain recovered units and prove the chosen layout reaches exact EOF."""
    if len(data) < 16 or data[:4] != b"W3do":
        return PlacementParseReport((), ("invalid placement header",))
    count = struct.unpack_from("<i", data, 12)[0]
    if count < 0:
        return PlacementParseReport((), (f"invalid placement count: {count}",))
    issues = _header_issues(data)
    # 不预拒绝截断文件的主表 count：逐条最低长度检查会按字节终止，保留已读实例。
    # 版本 7 = 经典 RoC（缺英雄三围 + 自定义颜色/传送门）；版本 8 = TFT。按版本号选布局，
    # 皮肤(重制版)仍两种都试取能读完的那个。版本 7 与版本 8 都覆盖到再扩展。
    version = struct.unpack_from("<i", data, 4)[0]
    v7 = version <= 7
    best: list[Unit] = []
    for skin in (False, True):  # 先经典后重制
        result, full = _attempt_units(data, count, skin, v7)
        if full:
            return PlacementParseReport(tuple(result), issues)
        if len(result) > len(best):
            best = result
    return PlacementParseReport(
        tuple(best),
        (
            *issues,
            f"recovered {len(best)} of {count} placements; no complete classic/reforged "
            "layout reaches EOF (unit table is truncated or has trailing bytes)",
        ),
    )
