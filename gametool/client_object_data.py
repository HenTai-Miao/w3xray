"""Snapshot base-object fields from a selected Warcraft client-data source."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import mmap
import os
import pickle
import sys
import tempfile
from pathlib import Path
from typing import Final, final

from .game_data_source import GameDataSource
from .object_candidates import ObjectFieldValue, collect_object_candidates
from .object_layers import binary_object_members
from .object_materialization import BaseObjectTable, merge_object_candidates
from .object_text_names import trusted_names
from .slk_objects import SLK_CATEGORY_FILES, _PREFIXES as _SLK_PREFIXES
from .wts import parse_wts

# 客户端快照内容不变（同一份游戏导出数据反复解析是纯浪费），
# 按全部输入文件的内容摘要做磁盘缓存；任何缓存异常都回退到现算。
_SNAPSHOT_CACHE_TAG: Final = (
    "gamexray-client-snapshot-v5"  # 完整空字段、SLK 分类及编辑器字段证据
)

_RACES: Final[tuple[str, ...]] = (
    "Human",
    "Orc",
    "NightElf",
    "Undead",
    "Neutral",
    "Campaign",
)
# 官方 Reforged 的中文文本挂在主模块内的 zhCN 语言包命名空间；
# 第二个前缀兼容部分导出工具的扁平布局。Func 等文件语言中立，不做变体。
_ZH_CN_PATH_PREFIXES: Final[tuple[str, ...]] = (
    "war3.w3mod:_locales\\zhcn.w3mod:",
    "zhcn.w3mod:",
)


def locale_text_candidates(name: str) -> tuple[str, ...]:
    """zhCN 语言包优先的读取候选；非 Strings 文本原样返回。"""
    if not name.casefold().endswith("strings.txt"):
        return (name,)
    return (*(prefix + name for prefix in _ZH_CN_PATH_PREFIXES), name)


_CLIENT_TEXT_NAMES: Final[tuple[str, ...]] = tuple(
    sorted(
        {
            *(
                f"Units\\{race}Unit{kind}.txt"
                for race in _RACES
                for kind in ("Func", "Strings")
            ),
            *(
                f"Units\\{race}Ability{kind}.txt"
                for race in (*_RACES, "Common", "Item")
                for kind in ("Func", "Strings")
            ),
            *(
                f"Units\\{race}Upgrade{kind}.txt"
                for race in _RACES
                for kind in ("Func", "Strings")
            ),
            "Units\\ItemFunc.txt",
            "Units\\ItemStrings.txt",
        },
        key=lambda name: (name.casefold(), name),
    )
)


@dataclass(frozen=True, slots=True)
class ClientBaseObject:
    """Immutable client fields retained after the native source closes."""

    obj_id: str
    category: str
    fields: tuple[tuple[str, str], ...]
    evidence_fields: tuple[ObjectFieldValue, ...] = ()


@dataclass(frozen=True, slots=True)
class ClientObjectSnapshot:
    """Closed-source-safe client objects and text availability."""

    objects: tuple[ClientBaseObject, ...]
    text_available: bool


@final
class _ClientObjectArchive:
    source: GameDataSource
    path: str
    _data: bytes | mmap.mmap
    _inputs: dict[str, bytes | None] | None

    def __init__(self, source: GameDataSource) -> None:
        self.source = source
        self.path = "client-data"
        self._data = b""
        self._inputs = None

    def _has_source_file(self, name: str) -> bool:
        if self._inputs is not None:
            return self._inputs.get(name) is not None
        return self.source.has_file(name)

    def has_file(self, name: str) -> bool:
        return any(self._has_source_file(path) for path in locale_text_candidates(name))

    def read_file(self, name: str) -> bytes:
        # 语言变体对采集器透明：请求名保持中立路径，优先读 zhCN 文本。
        for path in locale_text_candidates(name):
            if self._has_source_file(path):
                if self._inputs is not None:
                    payload = self._inputs[path]
                    assert payload is not None
                    return payload
                return self.source.read_file(path)
        if self._inputs is not None:
            raise FileNotFoundError(name)
        return self.source.read_file(name)

    def list_files(self) -> list[str]:
        return list(_CLIENT_TEXT_NAMES)

    def close(self) -> None:
        """The load-context owner closes the wrapped client source."""

    def capture_inputs(self) -> None:
        """Bind parsing to the exact named bytes included in the cache key."""
        inputs: dict[str, bytes | None] = {}

        def capture(name: str) -> bool:
            for path in locale_text_candidates(name):
                if path not in inputs:
                    inputs[path] = (
                        self.source.read_file(path)
                        if self.source.has_file(path)
                        else None
                    )
                if inputs[path] is not None:
                    return True
            return False

        for name in trusted_names(self, ()):
            capture(name)
        for prefix in ("war3map", "war3campaign"):
            for name in (*binary_object_members(prefix), f"{prefix}.wts"):
                capture(name)
        # Match the existing SLK reader's first present named alias. Keep every
        # preceding absence, so a newly available higher-priority alias changes
        # the key, without retaining repeated copies of the same large table.
        for files in SLK_CATEGORY_FILES.values():
            for name in files:
                aliases = (
                    prefix + variant
                    for prefix in _SLK_PREFIXES
                    for variant in dict.fromkeys((name, name.lower(), name.upper()))
                )
                for alias in aliases:
                    if capture(alias):
                        break
        self._inputs = dict(sorted(inputs.items()))

    def input_fingerprint(self) -> str:
        """Hash complete bytes, presence, names, and the extraction semantics."""
        assert self._inputs is not None
        digest = hashlib.sha256(_SNAPSHOT_CACHE_TAG.encode("ascii") + b"\0")
        for name, payload in self._inputs.items():
            encoded_name = name.encode("utf-8")
            digest.update(len(encoded_name).to_bytes(8, "little"))
            digest.update(encoded_name)
            digest.update(b"\0" if payload is None else b"\1")
            if payload is not None:
                digest.update(len(payload).to_bytes(8, "little"))
                digest.update(payload)
        return digest.hexdigest()

    def verify_inputs(self) -> None:
        """Never deliver or cache a snapshot whose source changed during the call."""
        if self._inputs is None:
            return
        for name, expected in self._inputs.items():
            current = (
                self.source.read_file(name) if self.source.has_file(name) else None
            )
            if current != expected:
                raise OSError(f"Warcraft client object source changed: {name}")


def collect_client_base_objects(
    source: GameDataSource | None,
) -> tuple[ClientBaseObject, ...]:
    """Parse complete named object tables without retaining the source handle."""
    return snapshot_client_base_objects(source).objects


def snapshot_client_base_objects(source: GameDataSource | None) -> ClientObjectSnapshot:
    """Snapshot every named client object source before its source closes.

    真实目录数据源默认启用内容寻址磁盘缓存；测试用假数据源不受影响。
    """
    if source is None:
        return ClientObjectSnapshot((), False)
    archive = _ClientObjectArchive(source)
    cache_path = _snapshot_cache_path(archive)
    text_available = any(archive.has_file(name) for name in _CLIENT_TEXT_NAMES)
    if cache_path is not None:
        cached = _load_snapshot_cache(cache_path)
        if cached is not None:
            archive.verify_inputs()
            return cached
    try:
        candidates = tuple(
            candidate
            for prefix in ("war3campaign", "war3map")
            for candidate in collect_object_candidates(
                archive, _client_wts(archive, prefix), prefix=prefix
            )
        )
    except OSError, ValueError:
        return ClientObjectSnapshot((), text_available)
    objects = merge_object_candidates(candidates, {})
    evidence_by_object: dict[tuple[str, str], list[ObjectFieldValue]] = {}
    for candidate in candidates:
        evidence_by_object.setdefault(
            (candidate.category, candidate.obj_id), []
        ).extend(
            candidate.fields,
        )
    snapshot = tuple(
        ClientBaseObject(
            item.obj_id,
            item.category,
            tuple((label, value) for label, value in item.fields if value),
            tuple(
                sorted(
                    evidence_by_object.get((item.category, item.obj_id), ()),
                    key=_evidence_sort_key,
                ),
            ),
        )
        for item in objects
        if len(item.obj_id) == 4
        and (item.fields or evidence_by_object.get((item.category, item.obj_id)))
    )
    result = ClientObjectSnapshot(snapshot, text_available)
    archive.verify_inputs()
    if cache_path is not None:
        _store_snapshot_cache(cache_path, result)
    return result


def _client_wts(archive: _ClientObjectArchive, prefix: str) -> dict[int, str]:
    name = f"{prefix}.wts"
    if not archive.has_file(name):
        return {}
    try:
        return parse_wts(archive.read_file(name))
    except KeyError, OSError, ValueError:
        return {}


def _snapshot_cache_path(archive: _ClientObjectArchive) -> Path | None:
    """内容寻址缓存键；仅真实盘上数据源且未显式禁用时启用。

    GAMEXRAY_SNAPSHOT_CACHE=0 关闭；GAMEXRAY_CACHE_DIR 指定缓存根目录。
    目录/CASC/MPQ 源的读取与内容摘要都很便宜（几 MB），
    省下的是每次加载重复付出的解析与合并（且一次加载会算两遍）。
    """
    if os.environ.get("GAMEXRAY_SNAPSHOT_CACHE", "1") != "1":
        return None
    from .game_data_source import (
        CascDataSource,
        CascLibDataSource,
        ClassicMpqDataSource,
        DirectoryDataSource,
        TrustedIconCacheDataSource,
    )

    if not isinstance(
        archive.source,
        (
            CascDataSource,
            CascLibDataSource,
            ClassicMpqDataSource,
            DirectoryDataSource,
            TrustedIconCacheDataSource,
        ),
    ):
        return None
    try:
        archive.capture_inputs()
    except KeyError, OSError, ValueError:
        return None
    cache_root = os.environ.get("GAMEXRAY_CACHE_DIR")
    if cache_root:
        base = Path(cache_root)
    elif sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        base = Path(os.environ["LOCALAPPDATA"]) / "gamexray" / "cache"
    else:
        base = Path(tempfile.gettempdir()) / "gamexray-cache"
    return base / "client-snapshots" / f"{archive.input_fingerprint()}.pkl"


def _load_snapshot_cache(path: Path) -> ClientObjectSnapshot | None:
    """命中则返回快照；任何缺失/损坏/不识别都返回 None 走现算。"""
    try:
        blob = path.read_bytes()
    except OSError:
        return None
    header, _, payload = blob.partition(b"\n")
    if header != _SNAPSHOT_CACHE_TAG.encode("ascii"):
        return None
    try:
        snapshot = pickle.loads(payload)
    except Exception:
        return None
    if isinstance(snapshot, ClientObjectSnapshot):
        return snapshot
    return None


def _store_snapshot_cache(path: Path, snapshot: ClientObjectSnapshot) -> None:
    """尽力写入；失败静默（缓存只加速，不影响正确性）。"""
    payload = pickle.dumps(snapshot, protocol=pickle.HIGHEST_PROTOCOL)
    blob = _SNAPSHOT_CACHE_TAG.encode("ascii") + b"\n" + payload
    temp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix="snapshot-", suffix=".tmp"
        )
        with os.fdopen(handle, "wb") as temp_file:
            temp_file.write(blob)
        os.replace(temp_name, path)
    except OSError:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass


def _evidence_sort_key(field: ObjectFieldValue) -> tuple[str, str, str, int, str]:
    return (
        field.key.casefold(),
        field.source.casefold(),
        field.source,
        int(field.source_kind),
        field.value,
    )


def merge_client_base_objects(
    base_objects: BaseObjectTable,
    client_objects: tuple[ClientBaseObject, ...],
) -> dict[str, tuple[str, tuple[tuple[str, str], ...]]]:
    """Fill missing bundled base fields from the selected client snapshot.

    相同快照值返回同一个合并表对象（值键 memo，客户端对象为 frozen 可哈希），
    并把稳定表注册给物化缓存复用；快照变化时旧表让位，驻留有界。
    """
    cache_key = client_objects
    per_table = _MERGED_TABLE_CACHE.get(id(base_objects))
    if (
        per_table is not None
        and _MERGED_TABLE_REFS.get(id(base_objects)) is base_objects
    ):
        cached = per_table.get(cache_key)
        if cached is not None:
            from .object_materialization import register_base_table_for_caching

            register_base_table_for_caching(cached)
            return cached
    merged = {
        code: (category, tuple((str(label), str(value)) for label, value in fields))
        for code, (category, fields) in base_objects.items()
    }
    for item in client_objects:
        existing = merged.get(item.obj_id)
        if existing is None:
            merged[item.obj_id] = (item.category, item.fields)
            continue
        category, fields = existing
        # Rawcodes can be reused by independent object categories. This legacy
        # base-table projection has one category per code; the complete client
        # snapshot retains the other category's fields separately.
        if category != item.category:
            continue
        combined = list(fields)
        labels = {label.casefold() for label, _value in combined}
        for label, value in item.fields:
            if label.casefold() not in labels:
                combined.append((label, value))
                labels.add(label.casefold())
        merged[item.obj_id] = (category, tuple(combined))
    if per_table is None:
        per_table = {}
        base_id = id(base_objects)
        if len(_MERGED_TABLE_CACHE) >= _MERGED_CACHE_LIMIT:
            _MERGED_TABLE_CACHE.clear()
            _MERGED_TABLE_REFS.clear()
        _MERGED_TABLE_CACHE[base_id] = per_table
        _MERGED_TABLE_REFS[base_id] = base_objects
    if len(per_table) >= _MERGED_CACHE_LIMIT:
        per_table.clear()
    per_table[cache_key] = merged
    from .object_materialization import register_base_table_for_caching

    register_base_table_for_caching(merged)
    return merged


_MERGED_CACHE_LIMIT: Final = 64
_MERGED_TABLE_CACHE: dict[
    int,
    dict[
        tuple[ClientBaseObject, ...], dict[str, tuple[str, tuple[tuple[str, str], ...]]]
    ],
] = {}
_MERGED_TABLE_REFS: dict[int, BaseObjectTable] = {}
