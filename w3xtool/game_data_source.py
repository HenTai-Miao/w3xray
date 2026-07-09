"""Runtime Warcraft III game-data directory sources."""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Protocol

from .casc_source import CascDataSource, has_casc_path_map


class GameDataSource(Protocol):
    """Common read interface for extracted and native game-data sources."""

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class GameDataProbe:
    kind: str
    is_readable: bool
    message: str


class DirectoryDataSource:
    """Read Reforged data exported to ordinary files."""

    def __init__(self, root: str):
        if not os.path.isdir(root):
            raise FileNotFoundError(root)
        self.root = root
        self._by_rel: dict[str, str] = {}
        self._by_base: dict[str, list[str]] = {}
        for dirpath, _dirs, files in os.walk(root):
            for filename in files:
                full = os.path.join(dirpath, filename)
                rel = os.path.relpath(full, root).replace("\\", "/").lower()
                self._by_rel[rel] = full
                self._by_base.setdefault(filename.lower(), []).append(rel)
        if not self._by_rel:
            raise FileNotFoundError(root)

    def has_file(self, name: str) -> bool:
        return self._resolve(name) is not None

    def read_file(self, name: str) -> bytes:
        path = self._resolve(name)
        if path is None:
            raise FileNotFoundError(name)
        with open(path, "rb") as handle:
            return handle.read()

    def _resolve(self, name: str) -> str | None:
        query = _norm(name)
        if query in self._by_rel:
            return self._by_rel[query]
        suffix_matches = [rel for rel in self._by_rel if rel.endswith("/" + query)]
        if suffix_matches:
            return self._by_rel[min(suffix_matches, key=len)]
        basename = query.rsplit("/", 1)[-1]
        base_matches = self._by_base.get(basename, [])
        if base_matches:
            return self._by_rel[min(base_matches, key=len)]
        return None


def probe_game_data_path(path: str | None) -> GameDataProbe:
    """Classify a user-selected game-data path."""
    if not path:
        return GameDataProbe("missing", False, "未选择游戏数据目录")
    if not os.path.isdir(path):
        return GameDataProbe("missing", False, "路径不存在")
    if _looks_like_native_casc(path):
        if has_casc_path_map(path):
            return GameDataProbe("native_casc", True, "原生 CASC 目录：使用路径映射直读 idx/data")
        return GameDataProbe("native_casc", False, "原生 CASC 已识别；缺路径索引，可提供 w3xray-casc-paths.tsv 或先导出散文件")
    if _has_any_file(path):
        return GameDataProbe("extracted_dir", True, "已导出的散文件目录")
    return GameDataProbe("empty", False, "目录为空")


def open_game_data_source(path: str | None) -> GameDataSource | None:
    """Open a readable game-data source chosen by the user."""
    probe = probe_game_data_path(path)
    if not probe.is_readable or path is None:
        return None
    if probe.kind == "native_casc":
        try:
            return CascDataSource(path)
        except (FileNotFoundError, OSError, ValueError):
            return None
    try:
        return DirectoryDataSource(path)
    except FileNotFoundError:
        return None


def _norm(name: str) -> str:
    return name.replace("\\", "/").lstrip("/").lower()


def _looks_like_native_casc(path: str) -> bool:
    data_dir = os.path.join(path, "Data", "data")
    if not os.path.isfile(os.path.join(path, ".build.info")):
        return False
    if not os.path.isdir(data_dir):
        return False
    try:
        names = os.listdir(data_dir)
    except OSError:
        return False
    has_index = any(name.lower().endswith(".idx") for name in names)
    has_data = any(name.lower().startswith("data.") for name in names)
    return has_index and has_data


def _has_any_file(path: str) -> bool:
    for _dirpath, _dirs, files in os.walk(path):
        if files:
            return True
    return False
