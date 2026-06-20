"""地图内嵌 SLK 文件的只读清单摘要。"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from .slk import parse_slk


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
    files: dict[str, bytes] = {}
    try:
        with MPQArchive(path) as archive:
            for name in archive.list_files():
                if name.lower().endswith(".slk") and archive.has_file(name):
                    files[name] = archive.read_file(name)
    except (OSError, ValueError, KeyError, UnicodeDecodeError):
        return SlkInventoryReport(())
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
