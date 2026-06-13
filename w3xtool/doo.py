"""预放置实例解析：war3map.doo（装饰物/可破坏物）、war3mapUnits.doo（单位）。

魔兽的"对象定义"（w3u/w3t/…，由 w3obj.py 解析）只说有哪些单位/物品；
.doo 才说这些东西"摆在地图哪、属于哪个玩家、初始多少血/金"。这是定义之外的另一维信息。

格式来源：
- 装饰物 doo：移植自 w3x2lni frontend_doo.lua；单位 doo（TFT 版本 8）按真实地图逐字节验证。
- **经典 vs 重制版**：两者同为 version 8/sub 11，但重制版每条记录在 scale 后多一个 4 字节皮肤码，
  无法靠版本号区分。故两种布局都试，取能完整读完所有 count 的那个（数据自适应）。已用真实
  重制版地图（27 张 Season1 对战图 + Darkborne RPG 33944 装饰物）逐字节验证（解析到 EOF）。
不可信文件：单条记录损坏/老格式变长尾部对不上时，保留已成功解析的实例后停止，
绝不抛、不死循环（与 w3obj.py 的逐对象容错一致）。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

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
        b = self.d[self.p:self.p + 4]
        self.p += 4
        return b.decode("latin-1")


@dataclass
class Doodad:
    type_id: str
    variation: int
    x: float
    y: float
    z: float
    angle: float                                  # 角度（度）
    scale: tuple = (1.0, 1.0, 1.0)
    flags: int = 0
    life: int = 100
    drops: list = field(default_factory=list)     # [(item_id, chance)]
    serial: int = 0


@dataclass
class Unit:
    type_id: str
    variation: int
    x: float
    y: float
    z: float
    angle: float                                  # 角度（度）
    player: int = 0
    hp: int = -1
    mana: int = -1
    gold: int = 0
    hero_level: int = 1
    items: list = field(default_factory=list)     # [(slot, item_id)]
    abilities: list = field(default_factory=list)  # [(ability_id, active, level)]
    serial: int = 0




def _read_doodad(r: _Reader, skin: bool) -> Doodad:
    """读一条装饰物记录。skin=True 时在 scale 后多读 4 字节皮肤码（重制版）。

    掉落数异常(>256 或 <0)判为布局错位 → 抛 ValueError，供上层换布局重试。
    """
    import math
    tid = r.tag()
    var = r.i32()
    x, y, z = r.f32(), r.f32(), r.f32()
    angle = math.degrees(r.f32())
    scale = (r.f32(), r.f32(), r.f32())
    if skin:
        r.tag()                                    # 重制版皮肤码 4 字节
    vis = r.u8()
    life = r.u8()
    r.i32()                                        # 掉落列表指针
    ndrops = r.i32()
    if ndrops < 0 or ndrops > 256:                 # 不合理 → 布局错位（如把 skin 当成了别的字段）
        raise ValueError("掉落数 %d 不合理" % ndrops)
    drops = []
    for _ in range(ndrops):
        drops.append((r.tag(), r.i32()))
    serial = r.i32()
    return Doodad(type_id=tid, variation=var, x=x, y=y, z=z, angle=angle,
                  scale=scale, flags=vis, life=life, drops=drops, serial=serial)


def _attempt_doodads(data: bytes, count: int, skin: bool):
    """按给定皮肤布局解析 count 个装饰物，返回 (列表, 是否完整读完所有 count)。"""
    r = _Reader(data)
    r.p = 16                                       # 跳过 magic+version+sub+count
    result = []
    for _ in range(count):
        try:
            result.append(_read_doodad(r, skin))
        except (struct.error, IndexError, ValueError):
            return result, False
    return result, True


def parse_doodads(data: bytes) -> list:
    """解析 war3map.doo，返回 Doodad 列表（仅装饰物主表，忽略特殊物）。

    经典与重制版同为 version 8/sub 11，但重制版每条多一个 4 字节皮肤码，无法靠版本区分。
    故两种布局都试，取能完整读完所有 count 的那个（数据自适应）；都不完整则返回读得更多的部分。
    """
    import sys
    if len(data) < 16 or data[:4] != b"W3do":
        return []
    try:
        count = struct.unpack_from("<i", data, 12)[0]
    except struct.error:
        return []
    if count < 0 or count > len(data):             # 注水 count
        return []
    best = []
    for skin in (False, True):                     # 先经典后重制
        result, full = _attempt_doodads(data, count, skin)
        if full:
            return result
        if len(result) > len(best):
            best = result
    if len(best) < count:
        print("[doo] war3map.doo 两种布局均未完整解析，保留 %d/%d 个装饰物"
              % (len(best), count), file=sys.stderr)
    return best


_CAP = 256          # 各 count 字段的合理上限：超过即判布局错位（换布局重试的信号）


def _read_unit(r: _Reader, skin: bool) -> Unit:
    """读一条单位记录（TFT 版本 8）。skin=True 时 scale 后多读 4 字节皮肤码（重制版）。

    各 count 超 _CAP 判为布局错位 → 抛 ValueError，供上层换布局重试。
    """
    import math
    tid = r.tag()
    var = r.i32()
    x, y, z = r.f32(), r.f32(), r.f32()
    angle = math.degrees(r.f32())
    r.f32(); r.f32(); r.f32()                      # scale x/y/z
    if skin:
        r.tag()                                    # 重制版皮肤码 4 字节
    r.u8()                                          # flags
    player = r.i32()
    r.u8(); r.u8()                                  # unknown ×2
    hp = r.i32()
    mana = r.i32()
    r.i32()                                         # dropped-item-set 指针
    nsets = r.i32()
    if nsets < 0 or nsets > _CAP:
        raise ValueError("dropset 数不合理")
    for _ in range(nsets):
        nitems = r.i32()
        if nitems < 0 or nitems > _CAP:
            raise ValueError("dropset 物品数不合理")
        for _ in range(nitems):
            r.tag(); r.i32()                        # item id + chance
    gold = r.i32()
    r.f32()                                         # 目标获取范围
    hlev = r.i32()
    r.i32(); r.i32(); r.i32()                       # 英雄 力量/敏捷/智力
    nitems = r.i32()
    if nitems < 0 or nitems > _CAP:
        raise ValueError("背包物品数不合理")
    items = []
    for _ in range(nitems):
        slot = r.i32()
        items.append((slot, r.tag()))
    nab = r.i32()
    if nab < 0 or nab > _CAP:
        raise ValueError("技能数不合理")
    abilities = []
    for _ in range(nab):
        aid = r.tag()
        active = r.i32()
        level = r.i32()
        abilities.append((aid, active, level))
    rflag = r.i32()
    if rflag == 0:
        r.i32()
    elif rflag == 1:
        r.i32(); r.i32()
    elif rflag == 2:
        n = r.i32()
        if n < 0 or n > _CAP:
            raise ValueError("随机组数不合理")
        for _ in range(n):
            r.tag(); r.i32()
    else:
        raise ValueError("未知 randomFlag %d" % rflag)
    r.i32()                                         # 自定义颜色
    r.i32()                                         # 传送门
    serial = r.i32()
    return Unit(type_id=tid, variation=var, x=x, y=y, z=z, angle=angle,
                player=player, hp=hp, mana=mana, gold=gold, hero_level=hlev,
                items=items, abilities=abilities, serial=serial)


def _attempt_units(data: bytes, count: int, skin: bool):
    """按给定皮肤布局解析 count 个单位，返回 (列表, 是否完整读完所有 count)。"""
    r = _Reader(data)
    r.p = 16                                        # 跳过 magic+version+sub+count
    result = []
    for _ in range(count):
        try:
            result.append(_read_unit(r, skin))
        except (struct.error, IndexError, ValueError):
            return result, False
    return result, True


def parse_units(data: bytes) -> list:
    """解析 war3mapUnits.doo，返回 Unit 列表。

    经典与重制版同为 version 8/sub 11，但重制版每条多一个 4 字节皮肤码（无法靠版本区分）。
    两种布局都试，取能完整读完所有 count 的那个；都不完整则返回读得更多的部分（老格式/损坏优雅降级）。
    """
    import sys
    if len(data) < 16 or data[:4] != b"W3do":
        return []
    try:
        count = struct.unpack_from("<i", data, 12)[0]
    except struct.error:
        return []
    if count < 0 or count > len(data):              # 注水 count
        return []
    best = []
    for skin in (False, True):                      # 先经典后重制
        result, full = _attempt_units(data, count, skin)
        if full:
            return result
        if len(result) > len(best):
            best = result
    if len(best) < count:
        print("[doo] war3mapUnits.doo 两种布局均未完整解析，保留 %d/%d 个单位"
              % (len(best), count), file=sys.stderr)
    return best
