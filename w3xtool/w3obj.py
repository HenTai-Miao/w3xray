"""解析魔兽对象编辑器数据（war3map.w3u/.w3t/.w3a/.w3q/.w3b/.w3d/.w3h）。

返回统一的对象列表：每个对象含 old_id / new_id / 是否自定义 / 字段修改。
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field

# 带 等级/变体 额外两个 int 的文件类型
_LEVEL_EXTS = {"w3a", "w3q", "w3d"}


def _decode_str(b: bytes) -> str:
    """字符串解码：优先 UTF-8（新版/重制版），失败回退 GBK（1.20~1.27 老中文图）。"""
    try:
        return b.decode("utf-8")
    except UnicodeDecodeError:
        try:
            return b.decode("gbk")
        except UnicodeDecodeError:
            return b.decode("utf-8", "replace")

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


@dataclass
class Modification:
    field_id: str
    var_type: int          # 0 int / 1 real / 2 unreal / 3 string
    level: int             # 仅 w3a/w3q/w3d 有意义，否则 0
    value: object


@dataclass
class W3Object:
    old_id: str            # 基础对象 4 字符码
    new_id: str            # 自定义新码（原始表为空）
    is_custom: bool
    mods: list = field(default_factory=list)


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
            r.u32()                  # setsFlag 位掩码，只读提取无需用到
        num_mods = r.i32()
        for _ in range(num_mods):
            field_id = r.tag()
            var_type = r.i32()
            level = 0
            if has_level:
                level = r.i32()
                r.i32()              # data pointer（列），忽略
            if var_type == 0:
                value = r.i32()
            elif var_type in (1, 2):
                value = r.f32()
            elif var_type == 3:
                value = r.cstr()
            else:
                raise ValueError("未知字段类型 %d @ %d" % (var_type, r.p))
            r.u32()                  # 末尾校验（=oldId/newId），跳过
            obj.mods.append(Modification(field_id, var_type, level, value))
    return obj


def parse_object_data(data: bytes, ext: str) -> list:
    """解析一个对象数据文件，返回 W3Object 列表。

    单个对象解析失败(截断/字节错位/未知字段类型/注水 count)不再拖垮整个文件：
    保留出错之前已成功解析的对象（出错后游标已不可信，停止该文件）。
    """
    import sys
    has_level = ext.lower() in _LEVEL_EXTS
    r = _Reader(data)
    objects: list = []
    try:
        version = r.i32()  # 1=RoC 2=TFT 3=1.32+/重制版（对象头改成 sets 分组）
    except (struct.error, IndexError):
        return objects
    for table_idx in range(2):           # 0=原始表 1=自定义表
        is_custom = table_idx == 1
        try:
            count = r.i32()
        except (struct.error, IndexError):
            break
        # 每个对象至少 ~8 字节：count 远超剩余字节即为损坏/注水，立即停止（防超大循环）。
        if count < 0 or count > len(r.d) - r.p:
            print("[w3obj] %s 对象数 %d 不合理（剩余 %d 字节），判为损坏"
                  % (ext, count, len(r.d) - r.p), file=sys.stderr)
            break
        for _ in range(count):
            start_p = r.p
            try:
                obj = _parse_one_object(r, is_custom, version, has_level)
            except (struct.error, IndexError, ValueError):
                print("[w3obj] %s 解析在偏移 %d 处中断，保留前 %d 个对象"
                      % (ext, start_p, len(objects)), file=sys.stderr)
                return objects
            objects.append(obj)
    return objects
