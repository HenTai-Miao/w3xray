"""MPQ archive file-name enumeration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Final, Protocol

from .imp import ImportTable, parse_import_table
from .war3_encoding import decode_warcraft_string


class FileListingArchive(Protocol):
    """Minimal archive API needed to enumerate known MPQ file names."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...


# 魔兽地图/战役固定内部文件名（listfile 被删时据此枚举）
# 借鉴 w3x2lni core/info.lua 的 impignore 清单；只有 has_file 验证存在的才会被收。
STATIC_MAP_FILES: Final[tuple[str, ...]] = (
    # 脚本 / 字符串
    "war3map.j", "war3map.lua", "war3map.wts",
    # 对象数据
    "war3map.w3u", "war3map.w3t", "war3map.w3a", "war3map.w3q",
    "war3map.w3b", "war3map.w3d", "war3map.w3h",
    # 触发器
    "war3map.wtg", "war3map.wct",
    # 地图信息 / 地形 / 预览
    "war3map.w3i", "war3map.w3e", "war3map.w3r", "war3map.w3c",
    "war3map.w3s", "war3map.wgc", "war3map.shd", "war3map.wpm", "war3map.mmp",
    "war3map.imp", "war3mapMap.blp", "war3mapMap.tga", "war3mapPath.tga",
    "war3mapPreview.tga", "war3mapPreview.blp",
    "war3mapUnits.doo", "war3map.doo",
    "testconfig.wgc",
    # 文本档
    "war3mapExtra.txt", "war3mapMisc.txt", "war3mapSkin.txt", "war3map.txt.ini",
    # MPQ 内部表
    "(listfile)", "(attributes)", "(signature)",
    # 战役级
    "war3campaign.w3f", "war3campaign.imp", "war3campaign.wts",
    "war3campaign.w3u", "war3campaign.w3t", "war3campaign.w3a",
    "war3campaign.w3q", "war3campaign.w3b", "war3campaign.w3d", "war3campaign.w3h",
)
IMPORT_TABLE_FILES: Final[tuple[str, ...]] = ("war3map.imp", "war3campaign.imp")


def list_archive_files(
    archive: FileListingArchive,
    external_names: Sequence[str] = (),
) -> list[str]:
    """Return known file names from (listfile), static names, and import tables."""
    names: list[str] = []
    seen: set[str] = set()

    _add_listfile_names(archive, names, seen)
    _add_external_names(archive, names, seen, external_names)
    for name in STATIC_MAP_FILES:
        _add_name(archive, names, seen, name, verify=True)
    _add_import_names(archive, names, seen)
    return names


def import_tables_from_archive(archive: FileListingArchive) -> tuple[ImportTable, ...]:
    """Parse every known map/campaign import table available in an archive."""
    tables: list[ImportTable] = []
    for table_name in IMPORT_TABLE_FILES:
        if not archive.has_file(table_name):
            continue
        try:
            tables.append(parse_import_table(archive.read_file(table_name)))
        except (KeyError, OSError, ValueError):
            continue
    return tuple(tables)


def import_path_candidate_groups(
    archive: FileListingArchive,
) -> tuple[tuple[str, ...], ...]:
    """Return candidate archive paths grouped by import table entry."""
    groups: list[tuple[str, ...]] = []
    for table in import_tables_from_archive(archive):
        groups.extend(entry.candidate_paths for entry in table.entries)
    return tuple(groups)


def import_candidate_names(archive: FileListingArchive) -> tuple[str, ...]:
    """Return all map/campaign import path candidates in archive order."""
    names: list[str] = []
    seen: set[str] = set()
    for candidates in import_path_candidate_groups(archive):
        for name in candidates:
            key = name.lower()
            if key in seen:
                continue
            seen.add(key)
            names.append(name)
    return tuple(names)


def _add_listfile_names(
    archive: FileListingArchive,
    names: list[str],
    seen: set[str],
) -> None:
    if not archive.has_file("(listfile)"):
        return
    try:
        text = decode_warcraft_string(archive.read_file("(listfile)"))
    except (KeyError, OSError, ValueError):
        return
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        _add_name(archive, names, seen, line.strip(), verify=False)


def _add_import_names(
    archive: FileListingArchive,
    names: list[str],
    seen: set[str],
) -> None:
    for candidates in import_path_candidate_groups(archive):
        for name in candidates:
            if archive.has_file(name):
                _add_name(archive, names, seen, name, verify=False)
                break


def _add_external_names(
    archive: FileListingArchive,
    names: list[str],
    seen: set[str],
    external_names: Sequence[str],
) -> None:
    for name in external_names:
        _add_name(archive, names, seen, name, verify=True)


def _add_name(
    archive: FileListingArchive,
    names: list[str],
    seen: set[str],
    name: str,
    *,
    verify: bool,
) -> None:
    if not name:
        return
    key = name.lower()
    if key in seen:
        return
    if verify and not archive.has_file(name):
        return
    seen.add(key)
    names.append(name)
