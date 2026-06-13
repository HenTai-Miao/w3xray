"""war3map.imp —— 地图导入文件清单解析。

很多优化/保护图把 (listfile) 删了，但 war3map.imp 仍记着每个自定义导入文件
（模型/图标/音效…）的路径。解析它能补出 listfile 缺失时拿不到的文件名。

格式（实测真实地图，与 w3x2lni 的 search_imp 一致）：
  int32 version, int32 count
  每条: 1 字节标志 + \\0 结尾的路径字符串
不可信文件：count 注水/数据截断时返回已成功读到的部分，绝不抛、不死循环。
"""
from __future__ import annotations

import struct


def parse_imp(data: bytes) -> list:
    """解析 war3map.imp，返回导入文件路径列表（保持原顺序、去空）。"""
    names: list = []
    if len(data) < 8:
        return names
    try:
        _version, count = struct.unpack_from("<ii", data, 0)
    except struct.error:
        return names
    p = 8
    # count 远超剩余字节即为注水/损坏（每条至少 2 字节：1 标志 + 1 终止符）→ 不进巨循环
    if count < 0 or count > (len(data) - p) // 2:
        count = max(0, (len(data) - p) // 2)
    for _ in range(count):
        if p >= len(data):
            break
        p += 1                                  # 跳过 1 字节标志
        end = data.find(b"\x00", p)
        if end < 0:                             # 缺终止符（尾部截断）：停止
            break
        name = data[p:end]
        p = end + 1
        try:
            s = name.decode("utf-8")
        except UnicodeDecodeError:
            s = name.decode("gbk", "replace")
        if s:
            names.append(s)
    return names
