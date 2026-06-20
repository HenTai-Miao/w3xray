"""资源依赖图：从对象字段、脚本和文件清单汇总素材引用。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .api import GameObject, MapData

RESOURCE_EXTS: Final = {
    "blp", "dds", "tga",
    "mdx", "mdl",
    "wav", "mp3", "ogg",
    "ttf",
}
_PATH_RE: Final = re.compile(
    r"(?i)([A-Za-z0-9_ .()\\/\-]{1,240}\."
    r"(?:blp|dds|tga|mdx|mdl|wav|mp3|ogg|ttf))"
)


@dataclass(frozen=True, slots=True)
class ResourceRef:
    source: str
    detail: str


@dataclass(frozen=True, slots=True)
class ResourceNode:
    path: str
    kind: str
    refs: tuple[ResourceRef, ...]


@dataclass(frozen=True, slots=True)
class ResourceReport:
    nodes: tuple[ResourceNode, ...]
    archive_assets: tuple[str, ...]
    unreferenced_assets: tuple[str, ...]

    @property
    def by_path(self) -> dict[str, ResourceNode]:
        return {node.path: node for node in self.nodes}


def build_resource_report(md: MapData) -> ResourceReport:
    """构建资源引用报告；仅使用 MapData 已解析内容。"""
    refs: dict[str, list[ResourceRef]] = {}
    for obj in _all_objects(md):
        _collect_object_refs(refs, obj)
    for script_name, text in sorted(md.scripts.items()):
        _collect_text_refs(refs, f"脚本 {script_name}", "字符串字面量", text)

    archive_assets = tuple(sorted(
        path for path in (_normalize(name) for name in getattr(md, "all_files", []) or [])
        if _is_asset(path)
    ))
    nodes = tuple(
        ResourceNode(path=path, kind=_kind_for(path), refs=tuple(items))
        for path, items in sorted(refs.items())
    )
    referenced = set(refs)
    unreferenced = tuple(path for path in archive_assets if path not in referenced)
    return ResourceReport(nodes, archive_assets, unreferenced)


def _all_objects(md: MapData) -> list[GameObject]:
    return [obj for group in md.objects.values() for obj in group]


def _collect_object_refs(refs: dict[str, list[ResourceRef]], obj: GameObject) -> None:
    if obj.icon:
        _add_ref(refs, obj.icon, ResourceRef(f"对象 {obj.obj_id}", "图标"))
    for label, value in obj.fields:
        _collect_text_refs(refs, f"对象 {obj.obj_id}", str(label), str(value))


def _collect_text_refs(
    refs: dict[str, list[ResourceRef]],
    source: str,
    detail: str,
    text: str,
) -> None:
    for match in _PATH_RE.finditer(text):
        _add_ref(refs, match.group(1), ResourceRef(source, detail))


def _add_ref(refs: dict[str, list[ResourceRef]], raw_path: str, ref: ResourceRef) -> None:
    path = _normalize(raw_path)
    if not _is_asset(path):
        return
    bucket = refs.setdefault(path, [])
    if ref not in bucket:
        bucket.append(ref)


def _normalize(path: str) -> str:
    normalized = path.strip().strip('"').strip("'").replace("/", "\\").lower()
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized


def _is_asset(path: str) -> bool:
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    return ext in RESOURCE_EXTS


def _kind_for(path: str) -> str:
    ext = path.rsplit(".", 1)[-1] if "." in path else ""
    if ext in {"blp", "dds", "tga"}:
        return "图像"
    if ext in {"mdx", "mdl"}:
        return "模型"
    if ext in {"wav", "mp3", "ogg"}:
        return "音频"
    if ext == "ttf":
        return "字体"
    return "资源"
