"""Resource body export for map knowledge packs."""

from __future__ import annotations

from dataclasses import dataclass
import os
import struct
from typing import TYPE_CHECKING, Final, Protocol

from .mpq import MPQArchive
from .resource_inventory import ResourceInventory, build_resource_inventory
from .safe_output import SafeWriteStatus, safe_relative_path, write_bytes_safely

if TYPE_CHECKING:
    from .api import MapData

_BODY_DIR: Final = "素材文件"


class _ReadableSource(Protocol):
    def read_file(self, name: str) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class AssetBodyExport:
    path: str
    exported_path: str
    size: int
    status: str


@dataclass(frozen=True, slots=True)
class AssetBodyExportReport:
    items: tuple[AssetBodyExport, ...]

    @property
    def exported_count(self) -> int:
        return sum(1 for item in self.items if item.status == "已导出")


class _DirectorySource:
    def __init__(self, root: str) -> None:
        self._root = os.path.realpath(root)
        self._files = _index_directory(self._root)

    def read_file(self, name: str) -> bytes:
        path = self._files.get(_normalize_path(name))
        if path is None:
            raise KeyError(name)
        with open(path, "rb") as handle:
            return handle.read()

    def close(self) -> None:
        return


def export_resource_bodies(
    md: MapData,
    resource_dir: str,
    inventory: ResourceInventory | None = None,
) -> AssetBodyExportReport:
    """Copy readable resource/config bodies into the knowledge pack."""
    resolved_inventory = inventory or build_resource_inventory(md)
    source = _open_source(md.path)
    rows: list[AssetBodyExport] = []
    try:
        for item in resolved_inventory.items:
            rows.append(_export_one(item.path, item.status, resource_dir, source))
    finally:
        if source is not None:
            source.close()
    return AssetBodyExportReport(tuple(rows))


def format_asset_body_manifest(report: AssetBodyExportReport) -> str:
    """Format copied body status as TSV."""
    rows = ["路径\t导出相对路径\t字节\t状态"]
    for item in report.items:
        rows.append("\t".join((
            _tsv(item.path),
            _tsv(item.exported_path),
            str(item.size),
            _tsv(item.status),
        )))
    return "\n".join(rows) + "\n"


def _export_one(
    path: str,
    status: str,
    resource_dir: str,
    source: _ReadableSource | None,
) -> AssetBodyExport:
    if not status.startswith("存在/"):
        return AssetBodyExport(path, "", 0, status)
    rel = _safe_body_relative(path)
    if rel is None:
        return AssetBodyExport(path, "", 0, "路径不安全")
    if source is None:
        return AssetBodyExport(path, "", 0, "源不可读")
    try:
        data = source.read_file(path)
    except KeyError:
        return AssetBodyExport(path, "", 0, "源内缺失")
    except (OSError, ValueError, struct.error):
        return AssetBodyExport(path, "", 0, "读取失败")
    result = write_bytes_safely(resource_dir, f"{_BODY_DIR}/{rel}", data)
    if result.status is SafeWriteStatus.UNSAFE:
        return AssetBodyExport(path, "", 0, "路径不安全")
    if result.status is SafeWriteStatus.FAILED:
        return AssetBodyExport(path, "", 0, "写入失败")
    return AssetBodyExport(path, f"{_BODY_DIR}/{rel}", len(data), "已导出")


def _open_source(path: str) -> _ReadableSource | None:
    if not path or not os.path.exists(path):
        return None
    if os.path.isdir(path):
        return _DirectorySource(path)
    try:
        return MPQArchive(path)
    except (OSError, ValueError, struct.error):
        return None


def _index_directory(root: str) -> dict[str, str]:
    files: dict[str, str] = {}
    for current, _dirnames, names in os.walk(root):
        for name in names:
            full_path = os.path.realpath(os.path.join(current, name))
            if os.path.commonpath([root, full_path]) != root:
                continue
            rel = os.path.relpath(full_path, root)
            files[_normalize_path(rel)] = full_path
    return files


def _safe_body_relative(path: str) -> str | None:
    relative = safe_relative_path(path)
    return relative.as_posix() if relative is not None else None


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').strip("'").replace("/", "\\").lower()
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
