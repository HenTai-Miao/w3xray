"""预放置实例解析：war3map.doo（装饰物/可破坏物）、war3mapUnits.doo（单位）。

魔兽的"对象定义"（w3u/w3t/…，由 w3obj.py 解析）只说有哪些单位/物品；
.doo 才说这些东西"摆在地图哪、属于哪个玩家、初始多少血/金"。这是定义之外的另一维信息。

格式来源：
- 装饰物 doo：移植自 w3x2lni frontend_doo.lua。
- 单位 doo（TFT 版本 8 / 子版本 11）：经 61/62 张真实地图逐字节验证（解析后恰好到 EOF）。
不可信文件：单条记录损坏/老格式（RoC v7）变长尾部对不上时，保留已成功解析的实例后停止，
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


def _check_head(r: _Reader, magic: bytes = b"W3do") -> bool:
    if len(r.d) < 16 or r.d[:4] != magic:
        return False
    return True


def parse_doodads(data: bytes) -> list:
    """解析 war3map.doo，返回 Doodad 列表（仅装饰物/可破坏物主表，忽略特殊物）。"""
    import math
    import sys
    r = _Reader(data)
    result: list = []
    if not _check_head(r):
        return result
    r.tag()                                       # 'W3do'
    r.i32()                                        # version
    r.i32()                                        # subversion(=11)
    try:
        count = r.i32()
    except (struct.error, IndexError):
        return result
    if count < 0 or count > len(r.d):              # 注水 count
        return result
    for _ in range(count):
        start = r.p
        try:
            tid = r.tag()
            var = r.i32()
            x, y, z = r.f32(), r.f32(), r.f32()
            angle = math.degrees(r.f32())
            scale = (r.f32(), r.f32(), r.f32())
            vis = r.u8()
            life = r.u8()
            r.i32()                                # 掉落列表指针
            ndrops = r.i32()
            drops = []
            if 0 < ndrops <= len(r.d):
                for _ in range(ndrops):
                    drops.append((r.tag(), r.i32()))
            serial = r.i32()
        except (struct.error, IndexError):
            print("[doo] war3map.doo 在偏移 %d 处中断，保留前 %d 个装饰物"
                  % (start, len(result)), file=sys.stderr)
            break
        result.append(Doodad(type_id=tid, variation=var, x=x, y=y, z=z,
                             angle=angle, scale=scale, flags=vis, life=life,
                             drops=drops, serial=serial))
    return result


def _read_unit(r: _Reader) -> Unit:
    """读取一条单位记录（TFT 版本 8 布局）。出错抛 struct.error/IndexError。"""
    import math
    tid = r.tag()
    var = r.i32()
    x, y, z = r.f32(), r.f32(), r.f32()
    angle = math.degrees(r.f32())
    r.f32(); r.f32(); r.f32()                      # scale x/y/z
    r.u8()                                          # flags
    player = r.i32()
    r.u8(); r.u8()                                  # unknown ×2
    hp = r.i32()
    mana = r.i32()
    r.i32()                                         # dropped-item-set 指针
    nsets = r.i32()
    if nsets < 0 or nsets > len(r.d):
        raise ValueError("dropset 数不合理")
    for _ in range(nsets):
        nitems = r.i32()
        if nitems < 0 or nitems > len(r.d):
            raise ValueError("dropset 物品数不合理")
        for _ in range(nitems):
            r.tag(); r.i32()                        # item id + chance
    gold = r.i32()
    r.f32()                                         # 目标获取范围
    hlev = r.i32()
    r.i32(); r.i32(); r.i32()                       # 英雄 力量/敏捷/智力
    nitems = r.i32()
    if nitems < 0 or nitems > len(r.d):
        raise ValueError("背包物品数不合理")
    items = []
    for _ in range(nitems):
        slot = r.i32()
        items.append((slot, r.tag()))
    nab = r.i32()
    if nab < 0 or nab > len(r.d):
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
        if n < 0 or n > len(r.d):
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


def parse_units(data: bytes) -> list:
    """解析 war3mapUnits.doo，返回 Unit 列表。

    单条记录损坏/老格式变长尾部对不上时，保留之前已成功解析的单位后停止（游标已不可信）。
    """
    import sys
    r = _Reader(data)
    result: list = []
    if not _check_head(r):
        return result
    r.tag()                                         # 'W3do'
    r.i32()                                          # version
    r.i32()                                          # subversion
    try:
        count = r.i32()
    except (struct.error, IndexError):
        return result
    if count < 0 or count > len(r.d):                # 注水 count
        return result
    for _ in range(count):
        start = r.p
        try:
            result.append(_read_unit(r))
        except (struct.error, IndexError, ValueError):
            print("[doo] war3mapUnits.doo 在偏移 %d 处中断，保留前 %d 个单位"
                  % (start, len(result)), file=sys.stderr)
            break
    return result
