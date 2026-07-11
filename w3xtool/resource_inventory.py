"""Resource/config inventory for investigation pack exports."""

from __future__ import annotations

from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from .imp import ImportSummary
from .presentation_safety import tsv_cell as _tsv
from .resources import build_resource_report

if TYPE_CHECKING:
    from .map_data import MapData

_IMAGE_EXTS: Final = {"blp", "dds", "tga", "png", "jpg", "jpeg", "bmp"}
_MODEL_EXTS: Final = {"mdx", "mdl"}
_AUDIO_EXTS: Final = {"wav", "mp3", "ogg"}
_FONT_EXTS: Final = {"ttf", "otf"}
_TEXT_EXTS: Final = {"txt", "ini", "wts", "fdf", "toc"}
_TEXT_CONFIG_EXTS: Final = {"json", "plist", "skin"}
_AI_EXTS: Final = {"ai"}
_OBJECT_EXTS: Final = {"w3u", "w3t", "w3a", "w3q", "w3b", "w3d", "w3h"}
_CONFIG_EXTS: Final = {"w3i", "w3f", "wgc"}
_SCRIPT_EXTS: Final = {"j", "lua", "wtg", "wct"}
_STRUCTURE_EXTS: Final = {"doo", "w3e", "wpm", "mmp", "w3r", "w3c", "w3s", "shd"}
_SOURCE_JOIN: Final = "；"


@dataclass(frozen=True, slots=True)
class ResourceInventoryItem:
    path: str
    kind: str
    status: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ResourceInventory:
    items: tuple[ResourceInventoryItem, ...]

    @property
    def kind_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(item.kind for item in self.items)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))

    @property
    def status_counts(self) -> tuple[tuple[str, int], ...]:
        counts = Counter(item.status for item in self.items)
        return tuple(sorted(counts.items(), key=lambda item: (-item[1], item[0])))


class ResourceContentRefLike(Protocol):
    @property
    def source_path(self) -> str: ...

    @property
    def target_path(self) -> str: ...


def build_resource_inventory(
    md: MapData,
    content_refs: Sequence[ResourceContentRefLike] = (),
) -> ResourceInventory:
    """Build a map investigation inventory from parsed files, imports, and refs."""
    sources_by_path: dict[str, set[str]] = {}
    existing_paths: set[str] = set()
    missing_paths: set[str] = set()
    referenced_paths: set[str] = set()

    for path in md.all_files:
        normalized = _normalize_path(str(path))
        if not _is_investigation_path(normalized):
            continue
        existing_paths.add(normalized)
        sources_by_path.setdefault(normalized, set()).add("内部文件")

    report = build_resource_report(md)
    for node in report.nodes:
        referenced_paths.add(node.path)
        bucket = sources_by_path.setdefault(node.path, set())
        for ref in node.refs:
            bucket.add(ref.source)
    for ref in content_refs:
        path = _normalize_path(ref.target_path)
        if not _is_investigation_path(path):
            continue
        referenced_paths.add(path)
        sources_by_path.setdefault(path, set()).add(f"素材内容 {ref.source_path}")

    _add_import_sources(md, sources_by_path, missing_paths)

    paths = set(sources_by_path) | existing_paths | referenced_paths | missing_paths
    items = tuple(
        ResourceInventoryItem(
            path=path,
            kind=_kind_for_path(path),
            status=_status_for(path, existing_paths, missing_paths, referenced_paths),
            sources=tuple(sorted(sources_by_path.get(path, ()))),
        )
        for path in sorted(paths)
    )
    return ResourceInventory(items)


def format_resource_inventory_tsv(inventory: ResourceInventory) -> str:
    """Format resource inventory as TSV for spreadsheets and diff reviews."""
    rows = ["路径\t类型\t状态\t来源"]
    for item in inventory.items:
        rows.append("\t".join((
            _tsv(item.path),
            _tsv(item.kind),
            _tsv(item.status),
            _tsv(_SOURCE_JOIN.join(item.sources)),
        )))
    return "\n".join(rows) + "\n"


def format_resource_inventory_summary(inventory: ResourceInventory) -> str:
    """Return compact inventory counts by kind and status."""
    lines = ["资源资产分类摘要", "按类型"]
    lines.extend(f"{kind}\t{count}" for kind, count in inventory.kind_counts)
    lines.append("")
    lines.append("按状态")
    lines.extend(f"{status}\t{count}" for status, count in inventory.status_counts)
    return "\n".join(lines) + "\n"


def _add_import_sources(
    md: MapData,
    sources_by_path: dict[str, set[str]],
    missing_paths: set[str],
) -> None:
    summary = getattr(md, "import_summary", None)
    if not isinstance(summary, ImportSummary):
        return

    resolved = {_normalize_path(path) for path in summary.resolved_paths}
    for entry in summary.entries:
        candidates = tuple(_normalize_path(path) for path in entry.candidate_paths)
        selected = next((path for path in candidates if path in resolved), None)
        selected_path = selected or (candidates[0] if candidates else _normalize_path(entry.path))
        sources_by_path.setdefault(selected_path, set()).add(f"导入表 {entry.type_label}")

    for path in summary.missing_paths:
        normalized = _normalize_path(path)
        missing_paths.add(normalized)
        sources_by_path.setdefault(normalized, set()).add("导入表缺失")


def _status_for(
    path: str,
    existing_paths: set[str],
    missing_paths: set[str],
    referenced_paths: set[str],
) -> str:
    if path in missing_paths and path not in existing_paths:
        return "导入缺失"
    if path in existing_paths and path in referenced_paths:
        return "存在/已引用"
    if path in existing_paths:
        return "存在/未引用"
    if path in referenced_paths:
        return "仅引用"
    return "仅登记"


def _is_investigation_path(path: str) -> bool:
    return _kind_for_path(path) != "其他"


def _kind_for_path(path: str) -> str:
    ext = _extension(path)
    name = path.rsplit("\\", 1)[-1]
    if ext in _IMAGE_EXTS:
        return "图标" if _looks_like_icon(path, name) else "图像"
    if ext in _MODEL_EXTS:
        return "模型"
    if ext in _AUDIO_EXTS:
        return "音频"
    if ext in _FONT_EXTS:
        return "字体"
    if ext in _TEXT_EXTS:
        return "UI/文本"
    if ext in _TEXT_CONFIG_EXTS:
        return "配置"
    if ext in _AI_EXTS:
        return "AI脚本"
    if ext == "slk":
        return "SLK表"
    if ext in _OBJECT_EXTS:
        return "对象数据"
    if ext in _CONFIG_EXTS:
        return "地图配置"
    if ext in _SCRIPT_EXTS:
        return "触发/脚本"
    if ext in _STRUCTURE_EXTS:
        return "地图结构"
    if ext == "imp":
        return "导入表"
    return "其他"


def _looks_like_icon(path: str, name: str) -> bool:
    return (
        "\\commandbuttons\\" in path
        or name.startswith(("btn", "disbtn", "pasbtn", "upg"))
    )


def _extension(path: str) -> str:
    if "." not in path:
        return ""
    return path.rsplit(".", 1)[-1].lower()


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').strip("'").replace("/", "\\").lower()
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized
