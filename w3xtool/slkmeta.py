"""地图内嵌 SLK 文件的只读清单摘要。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from .campaign_sources import open_map_source
from .map_archive_reader import MapArchiveReader
from .slk import parse_slk

if TYPE_CHECKING:
    from .map_data import MapData


@dataclass(frozen=True, slots=True)
class SlkFileSummary:
    path: str
    rows: int
    columns: int


@dataclass(frozen=True, slots=True)
class SlkInventoryReport:
    files: tuple[SlkFileSummary, ...]

    @property
    def has_data(self) -> bool:
        return bool(self.files)


def build_slk_inventory(files: Mapping[str, bytes]) -> SlkInventoryReport:
    """从内部文件 payload 构建 SLK 清单摘要。"""
    summaries: list[SlkFileSummary] = []
    for path, payload in sorted(files.items(), key=lambda item: item[0].lower()):
        if not path.lower().endswith(".slk"):
            continue
        summary = _summarize_slk(path, payload)
        if summary is not None:
            summaries.append(summary)
    return SlkInventoryReport(tuple(summaries))


def slk_inventory_from_map_path(path: str) -> SlkInventoryReport:
    """从地图 MPQ 中读取可枚举的 SLK 文件；失败时返回空清单。"""
    from .mpq import MPQArchive

    if not Path(path).is_file():
        return SlkInventoryReport(())
    try:
        with MPQArchive(path) as archive:
            return slk_inventory_from_archive(archive)
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        return SlkInventoryReport(())


def slk_inventory_from_map(md: MapData) -> SlkInventoryReport:
    """Read embedded SLK metadata through a loaded map's archive source."""
    if md.archive_source is None:
        return slk_inventory_from_map_path(md.path)
    try:
        with open_map_source(md) as archive:
            return slk_inventory_from_archive(archive)
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        return SlkInventoryReport(())


def slk_inventory_from_archive(archive: MapArchiveReader) -> SlkInventoryReport:
    """Build an SLK inventory from an already-open archive."""
    files: dict[str, bytes] = {}
    for name in archive.list_files():
        if name.lower().endswith(".slk") and archive.has_file(name):
            files[name] = archive.read_file(name)
    return build_slk_inventory(files)


def _summarize_slk(path: str, payload: bytes) -> SlkFileSummary | None:
    text = _decode_slk_payload(payload)
    rows: dict[str, dict[str, str]] = parse_slk(text)
    if not rows:
        return None
    columns = {col for row in rows.values() for col in row}
    return SlkFileSummary(path=path, rows=len(rows), columns=len(columns))


def _decode_slk_payload(payload: bytes) -> str:
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return payload.decode("latin-1")
