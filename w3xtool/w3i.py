"""war3map.w3i 地图信息解析（移植自 w3x2lni frontend_w3i.lua）。

w3i 是地图的"信息卡"：真实地图名/作者/描述、推荐人数、尺寸、对战/自定义标志、
脚本语言(JASS/Lua)、各玩家(类型/种族/开局点/名字)、队伍(同盟/共享)。w3xray 原来完全没解析。

版本：第一个 int32 即 file_version（18=RoC，25=TFT，28/31=重制版 1.31/1.32）。
本工具只取到玩家/队伍段（head 须读穿载入屏/雾/环境才能到玩家段）；之后的升级/科技/随机段不暴露、不解析。
不可信文件：任一段解析出错即停，保留已解析部分；版本不认/空数据返回 None。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

from .war3_encoding import decode_warcraft_string
from .wts import resolve

# 玩家类型 / 种族（编辑器口径）
PLAYER_TYPES = {1: "用户", 2: "电脑", 3: "中立", 4: "可救援"}
RACES = {0: "可选", 1: "人族", 2: "兽族", 3: "不死", 4: "暗夜", 5: "中立"}


@dataclass
class Player:
    id: int
    type: int
    race: int
    fixed_start: int
    name: str
    start_x: float = 0.0
    start_y: float = 0.0

    @property
    def type_name(self):
        return PLAYER_TYPES.get(self.type, str(self.type))

    @property
    def race_name(self):
        return RACES.get(self.race, str(self.race))


@dataclass
class Force:
    name: str
    allied: bool = False
    allied_victory: bool = False
    share_vision: bool = False
    share_control: bool = False
    players: list = field(default_factory=list)   # 玩家序号(1基) 列表


@dataclass
class W3iInfo:
    version: int = 0
    map_name: str = ""
    author: str = ""
    description: str = ""
    recommended_players: str = ""
    width: int = 0
    height: int = 0
    script_type: str = ""                          # 'JASS'/'Lua'/''(版本<28未记)
    # 配置标志
    disable_preview: bool = False
    custom_ally: bool = False
    melee: bool = False
    large_map: bool = False
    custom_forces: bool = False
    custom_techtree: bool = False
    custom_ability: bool = False
    custom_upgrade: bool = False
    players: list = field(default_factory=list)
    forces: list = field(default_factory=list)


@dataclass
class W3fInfo:
    version: int = 0
    campaign_version: int = 0
    editor_version: int = 0
    name: str = ""
    difficulty: str = ""
    author: str = ""
    description: str = ""


class _Reader:
    def __init__(self, data: bytes):
        self.d = data
        self.p = 0

    def i32(self) -> int:
        v = struct.unpack_from("<i", self.d, self.p)[0]
        self.p += 4
        return v

    def u32(self) -> int:
        v = struct.unpack_from("<I", self.d, self.p)[0]
        self.p += 4
        return v

    def f32(self) -> float:
        v = struct.unpack_from("<f", self.d, self.p)[0]
        self.p += 4
        return v

    def skip(self, n: int):
        if self.p + n > len(self.d):
            raise IndexError("skip 越界")
        self.p += n

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:
            end = len(self.d)
        b = self.d[self.p:end]
        self.p = end + 1
        return decode_warcraft_string(b)


def parse_w3i(data: bytes, wts: dict | None = None) -> "W3iInfo | None":
    wts = wts or {}
    if len(data) < 8:
        return None
    r = _Reader(data)

    def rs():                                       # 读 z 串并还原 TRIGSTR
        return str(resolve(r.cstr(), wts))

    try:
        version = r.i32()
    except (struct.error, IndexError):
        return None
    if version not in (18, 25, 28, 31):
        return None
    info = W3iInfo(version=version)
    try:
        r.i32()                                      # map_version
        r.i32()                                      # we_version
        if version >= 28:
            r.i32(); r.i32(); r.i32(); r.i32()       # war3 版本 4 段
        info.map_name = rs()
        info.author = rs()
        info.description = rs()
        info.recommended_players = rs()
        r.skip(8 * 4)                                # 镜头边界 8f
        r.skip(4 * 4)                                # 镜头补足 4i
        info.width = r.i32()
        info.height = r.i32()
        flag = r.u32()
        info.disable_preview = bool(flag & 0x1)
        info.custom_ally = bool(flag & 0x2)
        info.melee = bool(flag & 0x4)
        info.large_map = bool(flag & 0x8)
        info.custom_forces = bool(flag & 0x40)
        info.custom_techtree = bool(flag & 0x80)
        info.custom_ability = bool(flag & 0x100)
        info.custom_upgrade = bool(flag & 0x200)
        r.skip(1)                                    # c1 主地表

        if version >= 25:
            r.i32(); rs(); rs(); rs(); rs()          # 载入屏 id + 4z
            r.i32()                                  # game_data_set
            rs(); rs(); rs(); rs()                   # 序章 4z
            r.i32(); r.f32(); r.f32(); r.f32(); r.skip(4)   # 雾 type+3f+4B
            r.skip(4); rs(); r.skip(1); r.skip(4)    # 环境 weather c4 + sound z + light c1 + water 4B
            if version >= 28:
                info.script_type = "Lua" if r.i32() == 1 else "JASS"
            if version >= 31:
                r.i32(); r.i32()                     # 1.32 未知 8 字节
        elif version == 18:
            r.i32(); rs(); rs(); rs()                # 载入屏 id + 3z
            r.i32(); rs(); rs(); rs()                # 序章 id + 3z
    except (struct.error, IndexError):
        return info                                  # head 半截：返回已得字段

    # 玩家段
    try:
        pcount = r.i32()
        if 0 <= pcount <= len(r.d) - r.p:        # 每条至少 1 字节，按剩余字节卡上限
            for _ in range(pcount):
                pid = r.i32()
                ptype = r.i32()
                race = r.i32()
                fixed = r.i32()
                name = rs()
                sx = r.f32()
                sy = r.f32()
                r.u32(); r.u32()                     # ally low/high
                if version >= 31:
                    r.i32(); r.i32()                 # 1.32 未知
                info.players.append(Player(pid, ptype, race, fixed, name, sx, sy))
    except (struct.error, IndexError):
        return info

    # 队伍段
    try:
        fcount = r.i32()
        if 0 <= fcount <= len(r.d) - r.p:        # 每条至少 1 字节，按剩余字节卡上限
            for _ in range(fcount):
                fflag = r.u32()
                mask = r.u32()
                fname = rs()
                players = [i + 1 for i in range(32) if mask & (1 << i)]
                info.forces.append(Force(
                    name=fname,
                    allied=bool(fflag & 0x1),
                    allied_victory=bool(fflag & 0x2),
                    share_vision=bool(fflag & 0x8),
                    share_control=bool(fflag & 0x10),
                    players=players))
    except (struct.error, IndexError):
        return info

    return info


def parse_w3f(data: bytes, wts: dict | None = None) -> "W3fInfo | None":
    """解析 war3campaign.w3f 战役信息头（移植自 w3x2lni frontend_w3f.lua）。

    格式：i32 version + i32 campaign_version + i32 editor_version + z 名/难度/作者/描述。
    （KKWE 自身也只解到头，后续战役地图列表段暂不解析。）
    """
    wts = wts or {}
    if len(data) < 12:
        return None
    r = _Reader(data)
    try:
        info = W3fInfo(version=r.i32())
        info.campaign_version = r.i32()
        info.editor_version = r.i32()
        info.name = str(resolve(r.cstr(), wts))
        info.difficulty = str(resolve(r.cstr(), wts))
        info.author = str(resolve(r.cstr(), wts))
        info.description = str(resolve(r.cstr(), wts))
    except (struct.error, IndexError):
        return None
    return info
