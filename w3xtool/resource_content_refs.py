"""Second-level resource references found inside readable asset bodies."""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final, Protocol

from .mpq import MPQArchive
from .resources import find_resource_paths, resource_kind
from .war3_encoding import decode_warcraft_string

if TYPE_CHECKING:
    from .api import MapData

_TEXT_BODY_EXTS: Final = {"txt", "ini", "wts", "fdf", "toc", "slk", "json", "plist", "skin", "ai", "mdl"}
_MAX_SCAN_BYTES: Final = 2 * 1024 * 1024


class _ReadableSource(Protocol):
    def read_file(self, name: str) -> bytes: ...

    def close(self) -> None: ...


@dataclass(frozen=True, slots=True)
class ResourceContentReference:
    source_path: str
    target_path: str
    target_kind: str
    detail: str


@dataclass(frozen=True, slots=True)
class ResourceContentReferenceReport:
    items: tuple[ResourceContentReference, ...]


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


def build_resource_content_references(md: "MapData") -> ResourceContentReferenceReport:
    """Scan readable config/UI bodies for paths to other assets."""
    source = _open_source(md.path)
    if source is None:
        return ResourceContentReferenceReport(())
    refs: list[ResourceContentReference] = []
    seen: set[tuple[str, str]] = set()
    try:
        for path in _text_body_paths(tuple(getattr(md, "all_files", ()) or ())):
            _scan_one_body(source, path, refs, seen)
    finally:
        source.close()
    return ResourceContentReferenceReport(tuple(refs))


def format_resource_content_references_tsv(report: ResourceContentReferenceReport) -> str:
    """Format second-level resource references as TSV."""
    rows = ["来源文件\t引用路径\t引用类型\t说明"]
    for item in report.items:
        rows.append("\t".join((
            _tsv(item.source_path),
            _tsv(item.target_path),
            _tsv(item.target_kind),
            _tsv(item.detail),
        )))
    return "\n".join(rows) + "\n"


def _scan_one_body(
    source: _ReadableSource,
    path: str,
    refs: list[ResourceContentReference],
    seen: set[tuple[str, str]],
) -> None:
    try:
        raw = source.read_file(path)[:_MAX_SCAN_BYTES]
    except (KeyError, OSError, ValueError, struct.error):
        return
    text = decode_warcraft_string(raw, allow_latin1=True)
    for target in find_resource_paths(text):
        if target == path:
            continue
        key = (path, target)
        if key in seen:
            continue
        seen.add(key)
        refs.append(ResourceContentReference(path, target, resource_kind(target), "素材/配置文本内容"))


def _text_body_paths(names: tuple[str, ...]) -> tuple[str, ...]:
    paths = {
        _normalize_path(name)
        for name in names
        if _extension(name) in _TEXT_BODY_EXTS
    }
    return tuple(sorted(paths))


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
            files[_normalize_path(os.path.relpath(full_path, root))] = full_path
    return files


def _extension(path: str) -> str:
    return path.rsplit(".", 1)[-1].lower() if "." in path else ""


def _normalize_path(path: str) -> str:
    normalized = path.strip().strip('"').strip("'").replace("/", "\\").lower()
    while "\\\\" in normalized:
        normalized = normalized.replace("\\\\", "\\")
    return normalized


def _tsv(value: str) -> str:
    return value.replace("\t", " ").replace("\r", " ").replace("\n", " ")
