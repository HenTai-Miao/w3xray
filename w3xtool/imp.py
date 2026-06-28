"""war3map.imp —— 地图导入文件清单解析。

很多优化/保护图把 (listfile) 删了，但 war3map.imp 仍记着每个自定义导入文件
（模型/图标/音效…）的路径。解析它能补出 listfile 缺失时拿不到的文件名。

格式（实测真实地图，与 w3x2lni 的 search_imp 一致）：
  int32 version, int32 count
  每条: 1 字节标志 + \\0 结尾的路径字符串
不可信文件：count 注水/数据截断时返回已成功读到的部分，绝不抛、不死循环。
"""
from __future__ import annotations

from dataclasses import dataclass
import struct

IMPORTED_DIR = "war3mapImported\\"
STANDARD_IMPORT_TYPE = 8
CUSTOM_IMPORT_TYPE = 13


@dataclass(frozen=True, slots=True)
class ImportEntry:
    """One war3map.imp entry."""

    path: str
    flag: int

    @property
    def type_label(self) -> str:
        if self.flag == STANDARD_IMPORT_TYPE:
            return "标准路径"
        if self.flag == CUSTOM_IMPORT_TYPE:
            return "自定义路径"
        return f"未知({self.flag})"

    @property
    def is_custom_path(self) -> bool:
        return self.flag == CUSTOM_IMPORT_TYPE

    @property
    def is_standard_path(self) -> bool:
        return self.flag == STANDARD_IMPORT_TYPE

    @property
    def extension(self) -> str:
        name = self.path.rsplit("\\", 1)[-1].rsplit("/", 1)[-1]
        if "." not in name:
            return ""
        return name.rsplit(".", 1)[-1].lower()

    @property
    def candidate_paths(self) -> tuple[str, ...]:
        return import_candidate_paths(self)


@dataclass(frozen=True, slots=True)
class ImportTable:
    version: int
    entries: tuple[ImportEntry, ...]

    @property
    def entry_count(self) -> int:
        return len(self.entries)


@dataclass(frozen=True, slots=True)
class ImportSummary:
    version: int
    entries: tuple[ImportEntry, ...]
    resolved_paths: tuple[str, ...] = ()
    missing_paths: tuple[str, ...] = ()

    @property
    def entry_count(self) -> int:
        return len(self.entries)

    @property
    def standard_count(self) -> int:
        return sum(1 for entry in self.entries if entry.is_standard_path)

    @property
    def custom_count(self) -> int:
        return sum(1 for entry in self.entries if entry.is_custom_path)

    @property
    def unknown_count(self) -> int:
        return self.entry_count - self.standard_count - self.custom_count

    @property
    def extension_counts(self) -> tuple[tuple[str, int], ...]:
        counts: dict[str, int] = {}
        for entry in self.entries:
            ext = entry.extension or "(无扩展)"
            counts[ext] = counts.get(ext, 0) + 1
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


def parse_import_table(data: bytes) -> ImportTable:
    """解析 war3map.imp，保留版本、路径和导入类型标志。"""
    if len(data) < 8:
        return ImportTable(0, ())
    try:
        version, count = struct.unpack_from("<ii", data, 0)
    except struct.error:
        return ImportTable(0, ())
    p = 8
    # count 远超剩余字节即为注水/损坏（每条至少 2 字节：1 标志 + 1 终止符）→ 不进巨循环
    if count < 0 or count > (len(data) - p) // 2:
        count = max(0, (len(data) - p) // 2)
    entries: list[ImportEntry] = []
    for _ in range(count):
        if p >= len(data):
            break
        flag = data[p]
        p += 1
        end = data.find(b"\x00", p)
        if end < 0:
            break
        raw_name = data[p:end]
        p = end + 1
        try:
            path = raw_name.decode("utf-8")
        except UnicodeDecodeError:
            path = raw_name.decode("gbk", "replace")
        if path:
            entries.append(ImportEntry(path=path, flag=flag))
    return ImportTable(version, tuple(entries))


def parse_import_entries(data: bytes) -> tuple[ImportEntry, ...]:
    """解析 war3map.imp，返回结构化导入条目。"""
    return parse_import_table(data).entries


def parse_imp(data: bytes) -> list:
    """解析 war3map.imp，返回导入文件路径列表（保持原顺序、去空）。"""
    return [entry.path for entry in parse_import_entries(data)]


def import_candidate_paths(entry: ImportEntry) -> tuple[str, ...]:
    """Return archive path candidates for an imported file."""
    path = entry.path
    if not path:
        return ()
    prefixed = _with_imported_prefix(path)
    if entry.is_custom_path or _has_imported_prefix(path):
        return (path,)
    if entry.is_standard_path:
        return _dedupe((prefixed, path))
    return _dedupe((path, prefixed))


def _with_imported_prefix(path: str) -> str:
    if _has_imported_prefix(path):
        return path
    return IMPORTED_DIR + path


def _has_imported_prefix(path: str) -> bool:
    return path.replace("/", "\\").lower().startswith(IMPORTED_DIR.lower())


def _dedupe(paths: tuple[str, ...]) -> tuple[str, ...]:
    result = []
    seen = set()
    for path in paths:
        key = path.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(path)
    return tuple(result)
