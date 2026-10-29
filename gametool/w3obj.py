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
    var_type: int  # 0 int / 1 real / 2 unreal / 3 string
    level: int  # 仅 w3a/w3q/w3d 有意义，否则 0
    value: int | float | str
    data_pointer: int = 0
    offset: int = -1  # 源文件中的半开字节区间，包括字段头与末尾校验。
    end_offset: int = -1
    raw_bytes: bytes = b""
    trailer: int = 0


@dataclass(frozen=True, slots=True)
class W3Object:
    """Mutable object accumulator populated while parsing one table entry."""

    old_id: str  # 基础对象 4 字符码
    new_id: str  # 自定义新码（原始表为空）
    is_custom: bool
    mods: list[Modification] = field(default_factory=list)
    extra_ints: tuple[int, ...] = ()  # v3 对象头内的未知有符号整数数组。


@dataclass(frozen=True, slots=True)
class ObjectParseReport:
    """Recovered objects and complete reasons the source was incomplete."""

    objects: tuple[W3Object, ...]
    issues: tuple[str, ...]


class _ObjectParseFailure(ValueError):
    def __init__(
        self,
        reason: str,
        obj: W3Object | None,
        recovery_start: int,
        issues: tuple[str, ...],
    ) -> None:
        super().__init__(reason)
        self.obj = obj
        self.recovery_start = recovery_start
        self.issues = issues


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
        v = c_float.from_buffer_copy(self.d[self.p : end]).value
        self.p = end
        return v

    def _integer(self, *, signed: bool) -> int:
        end = self.p + 4
        if end > len(self.d):
            raise struct.error("truncated integer")
        value = int.from_bytes(self.d[self.p : end], "little", signed=signed)
        self.p = end
        return value

    def tag(self) -> str:
        end = self.p + 4
        if end > len(self.d):
            raise struct.error(f"truncated four-byte ID at {self.p}")
        b = self.d[self.p : end]
        self.p = end
        # 四字节身份按 Latin-1 原样保留，不限制为字母数字或 ASCII。
        return b.decode("latin-1")

    def cstr(self) -> str:
        end = self.d.find(b"\x00", self.p)
        if end < 0:
            raise struct.error(f"unterminated string at {self.p}")
        s = _decode_str(self.d[self.p : end])
        self.p = end + 1
        return s

    def eof(self) -> bool:
        return self.p >= len(self.d)


def _parse_modification(r: _Reader, has_level: bool) -> Modification:
    start = r.p
    field_id = r.tag()
    var_type = r.i32()
    level = r.i32() if has_level else 0
    data_pointer = r.i32() if has_level else 0
    if var_type == 0:
        value = r.i32()
    elif var_type in (1, 2):
        value = r.f32()
    elif var_type == 3:
        value = r.cstr()
    else:
        raise ValueError(f"unknown field type {var_type} at {start + 4}")
    trailer = r.u32()
    return Modification(
        field_id,
        var_type,
        level,
        value,
        data_pointer=data_pointer,
        offset=start,
        end_offset=r.p,
        raw_bytes=r.d[start : r.p],
        trailer=trailer,
    )


def _parse_one_object(
    r: _Reader, is_custom: bool, version: int, has_level: bool
) -> W3Object:
    """Retain completed modifications if a later part of this object fails."""
    obj: W3Object | None = None
    recovery_start = r.p + 1
    issues: list[str] = []
    try:
        old_id = r.tag()
        new_id = r.tag()
        extra_ints: tuple[int, ...] = ()
        if version >= 3:
            # War3Net 5f6f7bac26ed7ce7d0db83ceb4fb9ce59f918ff8,
            # Serialization/Binary/Object/{Simple,Level,Variation}ObjectModification:
            # old/new IDs, signed integer array, then ONE modification count.
            extra_offset = r.p
            extra_count = r.i32()
            remaining = len(r.d) - r.p
            if extra_count < 0 or extra_count * 4 + 4 > remaining:
                raise ValueError(
                    f"invalid extra-int count {extra_count} at {extra_offset} "
                    f"with {remaining} bytes remaining for integers and mod count"
                )
            extra_ints = tuple(r.i32() for _ in range(extra_count))
        obj = W3Object(old_id, new_id, is_custom, extra_ints=extra_ints)
        count_offset = r.p
        num_mods = r.i32()
        if num_mods < 0:
            raise ValueError(
                f"negative modification count {num_mods} at {count_offset}"
            )
        # Empty strings are the shortest supported values: 1 byte plus header
        # and trailer. Validate against bytes, not an arbitrary record ceiling.
        min_mod_size = 21 if has_level else 13
        remaining = len(r.d) - r.p
        if num_mods * min_mod_size > remaining:
            issues.append(
                f"invalid modification count {num_mods} at {count_offset} "
                f"with {remaining} bytes remaining (minimum {min_mod_size} per mod)"
            )
        for _ in range(num_mods):
            recovery_start = r.p
            obj.mods.append(_parse_modification(r, has_level))
    except (struct.error, IndexError, ValueError) as error:
        raise _ObjectParseFailure(
            f"{error}; reader offset {r.p}", obj, recovery_start, tuple(issues)
        ) from error
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
    scan_from: int,
) -> tuple[W3Object, int] | None:
    """坏对象后尝试重新同步到下一个可完整解析的对象头。"""
    limit = len(r.d) - _min_object_size(version) + 1
    for pos in range(scan_from, max(scan_from, limit)):
        if not (
            _looks_like_tag(r.d[pos : pos + 4])
            and _looks_like_tag(r.d[pos + 4 : pos + 8])
        ):
            continue
        trial = _Reader(r.d)
        trial.p = pos
        try:
            obj = _parse_one_object(trial, is_custom, version, has_level)
        except _ObjectParseFailure:
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
    注水 count 不再放弃整张表——以剩余字节量出对象数上界，解析到字节耗尽，
    一个不多一个不少。
    """
    return list(parse_object_data_report(data, ext).objects)


def parse_object_data_report(data: bytes, ext: str) -> ObjectParseReport:
    """Parse object data while retaining partial-result diagnostics."""
    has_level = ext.lower() in _LEVEL_EXTS
    r = _Reader(data)
    objects: list[W3Object] = []
    issues: list[str] = []
    try:
        version = r.i32()  # 1=RoC 2=TFT 3=1.32+（对象头增加未知整数数组）
    except struct.error, IndexError:
        return ObjectParseReport((), ("truncated object header",))
    if version not in {1, 2, 3}:
        return ObjectParseReport((), (f"unsupported object version: {version}",))
    for table_idx in range(2):  # 0=原始表 1=自定义表
        is_custom = table_idx == 1
        try:
            count = r.i32()
        except struct.error, IndexError:
            issues.append(f"truncated object table {table_idx}")
            break
        # 每个对象至少有对象头：count 远超剩余字节即为损坏/注水。防超大循环的
        # 手段是量出上界而非放弃——以剩余字节算出可达对象数，解析到字节耗尽。
        min_object_size = _min_object_size(version)
        if count < 0 or count * min_object_size > len(r.d) - r.p:
            reachable = max(0, (len(r.d) - r.p) // min_object_size)
            issues.append(
                f"invalid {ext} object count {count} with {len(r.d) - r.p} bytes "
                f"remaining; parsing table {table_idx} to end-of-data (≤{reachable} objects)",
            )
            count = reachable
        parsed_in_table = 0
        while parsed_in_table < count:
            start_p = r.p
            try:
                obj = _parse_one_object(r, is_custom, version, has_level)
            except _ObjectParseFailure as error:
                issues.extend(error.issues)
                retained = len(error.obj.mods) if error.obj is not None else 0
                if error.obj is not None and retained:
                    objects.append(error.obj)
                issues.append(
                    f"damaged {ext} object at {start_p}: {error}; "
                    f"retained {retained} confirmed modifications"
                )
                recovered = _recover_next_object(
                    r, is_custom, version, has_level, error.recovery_start
                )
                if recovered is not None:
                    obj, recovered_p = recovered
                    issues.append(
                        f"resumed {ext} table {table_idx} "
                        f"at object offset {recovered_p}"
                    )
                    objects.append(obj)
                    parsed_in_table = min(count, parsed_in_table + 2)
                    continue
                return ObjectParseReport(tuple(objects), tuple(issues))
            objects.append(obj)
            parsed_in_table += 1
    if r.p < len(data):
        issues.append(
            f"unconsumed {ext} trailing bytes at {r.p}: "
            f"{len(data) - r.p} bytes; raw_hex={data[r.p :].hex()}"
        )
    return ObjectParseReport(tuple(objects), tuple(issues))
