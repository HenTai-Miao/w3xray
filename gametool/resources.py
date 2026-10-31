"""资源依赖图：从对象字段、脚本和文件清单汇总素材引用。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from collections.abc import Iterable, Mapping, Sequence
from typing import Final, Protocol, cast

from .object_text_roles import classify_text_field
from .script_sources import analysis_script_sources
from .resource_types import (
    RESOURCE_EXTS as RESOURCE_EXTS,
    resource_kind as _resource_kind,
)


class _ResourceHost(Protocol):
    """Structural surface of MapData used here (avoids api import cycle)."""

    @property
    def objects(self) -> Mapping[str, Sequence[_ResourceObject]]: ...
    @property
    def all_files(self) -> list[str]: ...
    @property
    def _resource_report_cache(self) -> object: ...


class _ResourceObject(Protocol):
    @property
    def obj_id(self) -> str: ...

    @property
    def icon(self) -> str: ...

    @property
    def fields(self) -> Iterable[tuple[str, str]]: ...


_PATH_RE: Final = re.compile(
    r"(?i)([A-Za-z0-9_ .()\\/\-]+\."
    r"(?:blp|dds|tga|png|jpe?g|bmp|mdx|mdl|wav|mp3|ogg|ttf|otf|txt|ini|fdf|toc|"
    r"slk|json|plist|skin|ai))"
)
_TEXT_LABEL_KEYS: Final = {
    "说明": "display:description",
    "提示": "display:tip",
    "提示文本": "display:description",
    "扩展提示": "display:description",
    "工具提示": "display:tip",
}


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


@dataclass(frozen=True, slots=True)
class _ResourcePathIndex:
    """Match complete inventory spellings without scanning every asset per field."""

    nodes: tuple[dict[str, int], ...]
    terminals: dict[int, str]

    def spans(self, text: str) -> tuple[tuple[int, int, str], ...]:
        if not self.nodes[0] or "." not in text:
            return ()
        result: list[tuple[int, int, str]] = []
        start = 0
        while start < len(text):
            if start and _path_character(text[start - 1]):
                start += 1
                continue
            node = 0
            end = start
            match: tuple[int, int, str] | None = None
            while (
                end < len(text)
                and (child := self.nodes[node].get(text[end])) is not None
            ):
                node = child
                end += 1
                if node in self.terminals and (
                    end == len(text) or not _path_character(text[end])
                ):
                    match = (start, end, self.terminals[node])
            if match is None:
                start += 1
            else:
                result.append(match)
                start = match[1]
        return tuple(result)


def _path_character(char: str) -> bool:
    return char.isalnum() or char in "_.-/\\"


def _resource_path_index(paths: tuple[str, ...]) -> _ResourcePathIndex:
    nodes: list[dict[str, int]] = [{}]
    terminals: dict[int, str] = {}
    for path in paths:
        node = 0
        for char in path:
            child = nodes[node].get(char)
            if child is None:
                child = len(nodes)
                nodes[node][char] = child
                nodes.append({})
            node = child
        terminals[node] = path
    return _ResourcePathIndex(tuple(nodes), terminals)


def build_resource_report(md: _ResourceHost) -> ResourceReport:
    """构建资源引用报告；仅使用 MapData 已解析内容。

    报告是加载完成后的纯派生数据；分析页、审计、资料包各自调用，
    挂在 MapData 上的缓存让一次会话只构建一次。
    """
    cached = getattr(md, "_resource_report_cache", None)
    if cached is not None:
        return cast("ResourceReport", cached)
    # Keep this pure reference mirror on the same complete source-value proof
    # as archive discovery. The local import keeps kind/path-only callers
    # independent of script preparation and does not open an archive.
    from .resource_candidates import script_resource_candidates

    archive_assets = tuple(
        sorted(
            path
            for path in (
                _normalize(name) for name in getattr(md, "all_files", []) or []
            )
            if _is_asset(path)
        )
    )
    known_paths = _resource_path_index(archive_assets)
    refs: dict[str, list[ResourceRef]] = {}
    for obj in _all_objects(md):
        _collect_object_refs(refs, obj, known_paths)
    for script_name, text, lua in analysis_script_sources(md):  # pyright: ignore[reportArgumentType] - 结构兼容
        for candidate in script_resource_candidates(script_name, text, lua=lua):
            if candidate.state == "candidate":
                _add_ref(
                    refs,
                    candidate.path,
                    ResourceRef(f"脚本 {script_name}", "完整字符串字面量"),
                )

    nodes = tuple(
        ResourceNode(path=path, kind=_kind_for(path), refs=tuple(items))
        for path, items in sorted(refs.items())
    )
    referenced = set(refs)
    unreferenced = tuple(path for path in archive_assets if path not in referenced)
    report = ResourceReport(nodes, archive_assets, unreferenced)
    try:
        setattr(md, "_resource_report_cache", report)
    except AttributeError:  # 测试替身可能不是带槽的 MapData
        pass
    return report


def find_resource_paths(text: str) -> tuple[str, ...]:
    """Return normalized resource-like paths found in a text body."""
    comma_parts = tuple(_complete_resource_path(part) for part in text.split(","))
    if len(comma_parts) > 1 and all(part is not None for part in comma_parts):
        return tuple(dict.fromkeys(part for part in comma_parts if part is not None))
    whole = _complete_resource_path(text)
    matches = tuple(_PATH_RE.finditer(text))
    if whole is not None and len(matches) <= 1:
        return (whole,)
    paths: list[str] = []
    seen: set[str] = set()
    for match in matches:
        path = _normalize(match.group(1))
        if path in seen or not _is_asset(path):
            continue
        seen.add(path)
        paths.append(path)
    return tuple(paths)


def _complete_resource_path(text: str) -> str | None:
    whole = text.strip().strip('"').strip("'")
    if not whole or any(char in whole for char in "\r\n\t\"'"):
        return None
    normalized = _normalize(whole)
    return normalized if _is_asset(normalized) else None


def resource_kind(path: str) -> str:
    """Return the resource kind label for a path."""
    return _kind_for(_normalize(path))


def _all_objects(md: _ResourceHost) -> list[_ResourceObject]:
    return [obj for group in md.objects.values() for obj in group]


def _collect_object_refs(
    refs: dict[str, list[ResourceRef]],
    obj: _ResourceObject,
    known_paths: _ResourcePathIndex,
) -> None:
    if obj.icon:
        _add_ref(refs, obj.icon, ResourceRef(f"对象 {obj.obj_id}", "图标"))
    for label, value in obj.fields:
        _collect_text_refs(
            refs, f"对象 {obj.obj_id}", str(label), str(value), known_paths
        )


def _collect_text_refs(
    refs: dict[str, list[ResourceRef]],
    source: str,
    detail: str,
    text: str,
    known_paths: _ResourcePathIndex,
) -> None:
    normalized = _normalize(text)
    # Only declared text roles admit surrounding prose. A model or unknown
    # value may itself contain spaces/parentheses/semicolons; an inventory
    # basename inside it cannot replace the complete source path.
    role = classify_text_field("", _TEXT_LABEL_KEYS.get(detail, detail), detail)
    spans = known_paths.spans(normalized) if role is not None else ()
    if not spans:
        paths = find_resource_paths(text)
    else:
        retained: list[str] = []
        cursor = 0
        for start, end, path in spans:
            retained.extend(find_resource_paths(normalized[cursor:start].strip(" ,;")))
            retained.append(path)
            cursor = end
        retained.extend(find_resource_paths(normalized[cursor:].strip(" ,;")))
        paths = tuple(dict.fromkeys(retained))
    for path in paths:
        _add_ref(refs, path, ResourceRef(source, detail))


def _add_ref(
    refs: dict[str, list[ResourceRef]], raw_path: str, ref: ResourceRef
) -> None:
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
    return _resource_kind(path)
