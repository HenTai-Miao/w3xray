"""资源依赖图：从对象字段、脚本和文件清单汇总素材引用。"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from .api import GameObject, MapData

_IMAGE_EXTS: Final = {
    "blp", "dds", "tga", "png", "jpg", "jpeg", "bmp",
}
_MODEL_EXTS: Final = {
    "mdx", "mdl",
}
_AUDIO_EXTS: Final = {
    "wav", "mp3", "ogg",
}
_FONT_EXTS: Final = {
    "ttf", "otf",
}
_UI_TEXT_EXTS: Final = {
    "txt", "ini", "fdf", "toc",
}
_TABLE_EXTS: Final = {
    "slk",
}
_CONFIG_EXTS: Final = {
    "json", "plist", "skin",
}
_AI_EXTS: Final = {
    "ai",
}
RESOURCE_EXTS: Final = (
    _IMAGE_EXTS | _MODEL_EXTS | _AUDIO_EXTS | _FONT_EXTS | _UI_TEXT_EXTS
    | _TABLE_EXTS | _CONFIG_EXTS | _AI_EXTS
)
_PATH_RE: Final = re.compile(
    r"(?i)([A-Za-z0-9_ .()\\/\-]{1,240}\."
    r"(?:blp|dds|tga|png|jpe?g|bmp|mdx|mdl|wav|mp3|ogg|ttf|otf|txt|ini|fdf|toc|"
    r"slk|json|plist|skin|ai))"
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


def find_resource_paths(text: str) -> tuple[str, ...]:
    """Return normalized resource-like paths found in a text body."""
    paths: list[str] = []
    seen: set[str] = set()
    for match in _PATH_RE.finditer(text):
        path = _normalize(match.group(1))
        if path in seen or not _is_asset(path):
            continue
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def resource_kind(path: str) -> str:
    """Return the resource kind label for a path."""
    return _kind_for(_normalize(path))


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
    if ext in _IMAGE_EXTS:
        return "图像"
    if ext in _MODEL_EXTS:
        return "模型"
    if ext in _AUDIO_EXTS:
        return "音频"
    if ext in _FONT_EXTS:
        return "字体"
    if ext in _UI_TEXT_EXTS:
        return "UI/文本"
    if ext in _TABLE_EXTS:
        return "SLK表"
    if ext in _CONFIG_EXTS:
        return "配置"
    if ext in _AI_EXTS:
        return "AI脚本"
    return "资源"
