"""Resource body export for map knowledge packs."""

from __future__ import annotations

from dataclasses import dataclass
import os
import struct
from contextlib import nullcontext
from typing import TYPE_CHECKING, ContextManager, Final, Protocol, final

from .campaign_sources import open_map_source
from .resource_inventory import ResourceInventory, ResourceInventoryItem, build_resource_inventory
from .safe_output import safe_relative_path, write_bytes_safely
from .safe_output_models import SafeWriteStatus

if TYPE_CHECKING:
    from .game_data_source import GameDataSource
    from .map_data import MapData

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
    source: str = ""


@dataclass(frozen=True, slots=True)
class AssetBodyExportReport:
    items: tuple[AssetBodyExport, ...]

    @property
    def exported_count(self) -> int:
        return sum(1 for item in self.items if item.status == "已导出")


@final
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
    *,
    game_data_source: GameDataSource | None = None,
) -> AssetBodyExportReport:
    """Copy readable resource/config bodies into the knowledge pack."""
    resolved_inventory = inventory or build_resource_inventory(md)
    source_context = _open_source(md)
    if source_context is None:
        return _export_items(resolved_inventory, resource_dir, None, game_data_source)
    try:
        with source_context as source:
            return _export_items(resolved_inventory, resource_dir, source, game_data_source)
    except (OSError, ValueError, struct.error):
        return _export_items(resolved_inventory, resource_dir, None, game_data_source)


def format_asset_body_manifest(report: AssetBodyExportReport) -> str:
    """Format copied body status as TSV."""
    rows = ["路径\t导出相对路径\t字节\t状态\t来源"]
    for item in report.items:
        rows.append("\t".join((
            _tsv(item.path),
            _tsv(item.exported_path),
            str(item.size),
            _tsv(item.status),
            _tsv(item.source),
        )))
    return "\n".join(rows) + "\n"


def _export_items(
    inventory: ResourceInventory,
    resource_dir: str,
    map_source: _ReadableSource | None,
    game_data_source: GameDataSource | None,
) -> AssetBodyExportReport:
    return AssetBodyExportReport(
        tuple(
            _export_inventory_item(item, resource_dir, map_source, game_data_source)
            for item in inventory.items
        )
    )


def _export_inventory_item(
    item: ResourceInventoryItem,
    resource_dir: str,
    map_source: _ReadableSource | None,
    game_data_source: GameDataSource | None,
) -> AssetBodyExport:
    if item.status.startswith("存在/"):
        return _export_one(item.path, resource_dir, map_source, "地图数据")
    if _is_referenced_object_icon(item) and game_data_source is not None:
        result = _export_one(item.path, resource_dir, game_data_source, "客户端数据")
        if result.status != "源内缺失":
            return result
    return AssetBodyExport(item.path, "", 0, item.status)


def _export_one(
    path: str,
    resource_dir: str,
    source: _ReadableSource | None,
    source_label: str,
) -> AssetBodyExport:
    rel = _safe_body_relative(path)
    if rel is None:
        return AssetBodyExport(path, "", 0, "路径不安全", source_label)
    if source is None:
        return AssetBodyExport(path, "", 0, "源不可读", source_label)
    try:
        data = source.read_file(path)
    except (FileNotFoundError, KeyError):
        return AssetBodyExport(path, "", 0, "源内缺失", source_label)
    except (OSError, ValueError, struct.error):
        return AssetBodyExport(path, "", 0, "读取失败", source_label)
    result = write_bytes_safely(resource_dir, f"{_BODY_DIR}/{rel}", data)
    if result.status is SafeWriteStatus.UNSAFE:
        return AssetBodyExport(path, "", 0, "路径不安全", source_label)
    if result.status is SafeWriteStatus.FAILED:
        return AssetBodyExport(path, "", 0, "写入失败", source_label)
    return AssetBodyExport(path, f"{_BODY_DIR}/{rel}", len(data), "已导出", source_label)


def _is_referenced_object_icon(item: ResourceInventoryItem) -> bool:
    return item.kind == "图标" and any(source.startswith("对象 ") for source in item.sources)


def _open_source(md: MapData) -> ContextManager[_ReadableSource] | None:
    if md.path and os.path.isdir(md.path):
        return nullcontext(_DirectorySource(md.path))
    try:
        return open_map_source(md)
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
