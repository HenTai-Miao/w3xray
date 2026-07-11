"""解析魔兽对象编辑器数据（war3map.w3u/.w3t/.w3a/.w3q/.w3b/.w3d/.w3h）。

返回统一的对象列表：每个对象含 old_id / new_id / 是否自定义 / 字段修改。
"""
from __future__ import annotations

import struct
from ctypes import c_float
from dataclasses import dataclass, field

from .war3_encoding import decode_warcraft_string

# 带 等级/变体 额外两个 int 的文件类型
_LEVEL_EXTS = {"w3a", "w3q", "w3d"}


def _decode_str(b: bytes) -> str:
    """字符串解码：UTF-8 后按系统 ACP/GBK 兼容老图。"""
    return decode_warcraft_string(b)

# 文件扩展名 → 中文分类名
EXT_CATEGORY = {
    "w3u": "单位",
    "w3t": "物品",
    "w3a": "技能",
    "w3q": "科技",
    "w3b": "可破坏物",
    "w3d": "装饰物",
    "w3h": "增益",
}


@dataclass(frozen=True, slots=True)
class Modification:
    field_id: str
    var_type: int          # 0 int / 1 real / 2 unreal / 3 string
    level: int             # 仅 w3a/w3q/w3d 有意义，否则 0
    value: int | float | str


@dataclass(frozen=True, slots=True)
class W3Object:
    """Mutable object accumulator populated while parsing one table entry."""

    old_id: str            # 基础对象 4 字符码
    new_id: str            # 自定义新码（原始表为空）
    is_custom: bool
    mods: list[Modification] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ObjectParseReport:
    """Recovered objects plus bounded reasons the source was incomplete."""

    objects: tuple[W3Object, ...]
    issues: tuple[str, ...]


class _Reader:
    def __init__(self, data: bytes):
        self.d: bytes = data
        self.p: int = 0

    def i32(self) -> int:
        return self._integer(signed=True)

    def u32(self) -> int:
        return self._integer(signed=False)

    def f32(self) -> float:
        end = self.p + 4
        if end > len(self.d):
            raise struct.error("truncated float")
        v = c_float.from_buffer_copy(self.d[self.p:end]).value
        self.p = end
        return v

    def _integer(self, *, signed: bool) -> int:
        end = self.p + 4
        if end > len(self.d):
            raise struct.error("truncated integer")
        value = int.from_bytes(self.d[self.p:end], "little", signed=signed)
        self.p = end
        return value

    def tag(self) -> str:
        b = self.d[self.p:self.p + 4]
        self.p += 4
        # 4 字符码，按 latin-1 还原（魔兽里都是 ASCII）
        return b.decode("latin-1")

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:                       # 缺终止符(尾部截断)：读到结尾兜底，不抛异常
            end = len(self.d)
        s = _decode_str(self.d[self.p:end])
        self.p = end + 1
        return s

    def eof(self) -> bool:
        return self.p >= len(self.d)


def _parse_one_object(r: _Reader, is_custom: bool, version: int, has_level: bool) -> W3Object:
    """解析单个对象。出错(截断/错位/未知类型)时抛 struct.error/IndexError/ValueError，
    由 parse_object_data 统一兜住——保留之前已成功的对象。"""
    old_id = r.tag()
    new_id = r.tag()
    obj = W3Object(old_id=old_id, new_id=new_id, is_custom=is_custom)
    # 格式 3（重制版）：oldId/newId 后是 sets 数量，再按 set 循环
    #   每个 set = setsFlag(u32 位掩码，HD/SD 皮肤分组) + 该 set 的修改数 + 修改项
    # 格式 1/2：没有 sets 概念，等价于单个 set（无 setsFlag）。
    num_sets = r.u32() if version >= 3 else 1
    for _ in range(num_sets):
        if version >= 3:
            _ = r.u32()              # setsFlag 位掩码，只读提取无需用到
        num_mods = r.i32()
        for _ in range(num_mods):
            field_id = r.tag()
            var_type = r.i32()
            level = 0
            if has_level:
                level = r.i32()
                _ = r.i32()          # data pointer（列），忽略
            if var_type == 0:
                value = r.i32()
            elif var_type in (1, 2):
                value = r.f32()
            elif var_type == 3:
                value = r.cstr()
            else:
                raise ValueError("未知字段类型 %d @ %d" % (var_type, r.p))
            _ = r.u32()              # 末尾校验（=oldId/newId），跳过
            obj.mods.append(Modification(field_id, var_type, level, value))
    return obj


def _min_object_size(version: int) -> int:
    return 16 if version >= 3 else 12


def _looks_like_tag(raw: bytes) -> bool:
    return len(raw) == 4 and all(0x20 <= b < 0x7F for b in raw)


def _recover_next_object(
    r: _Reader,
    is_custom: bool,
    version: int,
    has_level: bool,
    start_p: int,
) -> tuple[W3Object, int] | None:
    """坏对象后尝试重新同步到下一个可完整解析的对象头。"""
    limit = len(r.d) - _min_object_size(version) + 1
    for pos in range(start_p + 1, max(start_p + 1, limit)):
        if not (_looks_like_tag(r.d[pos:pos + 4]) and _looks_like_tag(r.d[pos + 4:pos + 8])):
            continue
        trial = _Reader(r.d)
        trial.p = pos
        try:
            obj = _parse_one_object(trial, is_custom, version, has_level)
        except (struct.error, IndexError, ValueError):
            continue
        if not obj.mods:
            continue
        r.p = trial.p
        return obj, pos
    return None


def parse_object_data(data: bytes, ext: str) -> list[W3Object]:
    """解析一个对象数据文件，返回 W3Object 列表。

    单个对象解析失败(截断/字节错位/未知字段类型/注水 count)不再拖垮整个文件：
    保留出错之前已成功解析的对象，并尽量重同步到后续完整对象。
    """
    return list(parse_object_data_report(data, ext).objects)


def parse_object_data_report(data: bytes, ext: str) -> ObjectParseReport:
    """Parse object data while retaining partial-result diagnostics."""
    has_level = ext.lower() in _LEVEL_EXTS
    r = _Reader(data)
    objects: list[W3Object] = []
    issues: list[str] = []
    try:
        version = r.i32()  # 1=RoC 2=TFT 3=1.32+/重制版（对象头改成 sets 分组）
    except (struct.error, IndexError):
        return ObjectParseReport((), ("truncated object header",))
    if version not in {1, 2, 3}:
        return ObjectParseReport((), (f"unsupported object version: {version}",))
    for table_idx in range(2):           # 0=原始表 1=自定义表
        is_custom = table_idx == 1
        try:
            count = r.i32()
        except (struct.error, IndexError):
            issues.append(f"truncated object table {table_idx}")
            break
        # 每个对象至少有对象头：count 远超剩余字节即为损坏/注水，立即停止（防超大循环）。
        min_object_size = _min_object_size(version)
        if count < 0 or count * min_object_size > len(r.d) - r.p:
            issues.append(
                f"invalid {ext} object count {count} with {len(r.d) - r.p} bytes remaining",
            )
            break
        parsed_in_table = 0
        while parsed_in_table < count:
            start_p = r.p
            try:
                obj = _parse_one_object(r, is_custom, version, has_level)
            except (struct.error, IndexError, ValueError):
                recovered = _recover_next_object(r, is_custom, version, has_level, start_p)
                if recovered is not None:
                    obj, recovered_p = recovered
                    issues.append(f"skipped damaged {ext} object at {start_p}, resumed at {recovered_p}")
                    objects.append(obj)
                    parsed_in_table = min(count, parsed_in_table + 2)
                    continue
                issues.append(f"truncated {ext} object at {start_p}; recovered {len(objects)} objects")
                return ObjectParseReport(tuple(objects), tuple(issues))
            objects.append(obj)
            parsed_in_table += 1
    return ObjectParseReport(tuple(objects), tuple(issues))
