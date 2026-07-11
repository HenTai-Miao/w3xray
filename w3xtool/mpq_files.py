"""MPQ archive file-name enumeration helpers."""

from __future__ import annotations

from collections.abc import Sequence
from io import StringIO
from typing import TYPE_CHECKING, Final, Protocol

from .external_listfile import (
    MAX_EXTERNAL_LISTFILE_BYTES,
    MAX_EXTERNAL_LISTFILE_ENTRIES,
    MAX_EXTERNAL_LISTFILE_LINE_CHARS,
)
from .extraction_diagnostics import read_component, record_component_parse_issue
from .imp import ImportTable, import_table_parse_issue, parse_import_table
from .map_archive_reader import DeclaredSizeArchive
from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .map_data import MapData

_MAX_LISTFILE_BYTES: Final = MAX_EXTERNAL_LISTFILE_BYTES
_MAX_LISTFILE_NAMES: Final = MAX_EXTERNAL_LISTFILE_ENTRIES
_MAX_LISTFILE_LINE_CHARS: Final = MAX_EXTERNAL_LISTFILE_LINE_CHARS
_MAX_ARCHIVE_NAME_CHARS: Final = 1024


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


def import_tables_from_archive(
    archive: FileListingArchive,
    *,
    md: MapData | None = None,
) -> tuple[ImportTable, ...]:
    """Parse every known map/campaign import table available in an archive."""
    tables: list[ImportTable] = []
    for table_name in IMPORT_TABLE_FILES:
        if not archive.has_file(table_name):
            continue
        if md is not None:
            payload = read_component(
                md,
                "imp",
                table_name,
                lambda source=table_name: archive.read_file(source),
                stage="read",
            )
            if payload is None:
                continue
            table = parse_import_table(payload)
            issue = import_table_parse_issue(payload, table)
            if issue is not None:
                record_component_parse_issue(md, "imp", table_name, issue)
            tables.append(table)
        else:
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
    if isinstance(archive, DeclaredSizeArchive):
        declared_size = archive.declared_file_size("(listfile)")
        if declared_size is not None and declared_size > _MAX_LISTFILE_BYTES:
            return
    try:
        payload = archive.read_file("(listfile)")
    except (KeyError, OSError, ValueError):
        return
    if len(payload) > _MAX_LISTFILE_BYTES:
        return
    text = decode_warcraft_string(payload)
    with StringIO(text, newline=None) as lines:
        for index, raw_line in enumerate(lines):
            if index >= _MAX_LISTFILE_NAMES:
                break
            line = raw_line.rstrip("\r\n")
            if len(line) <= _MAX_LISTFILE_LINE_CHARS:
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
    if not name or len(name) > _MAX_ARCHIVE_NAME_CHARS:
        return
    key = name.lower()
    if key in seen:
        return
    if verify and not archive.has_file(name):
        return
    seen.add(key)
    names.append(name)
