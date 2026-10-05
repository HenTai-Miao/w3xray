"""Materialize normalized object candidates into public map objects."""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from concurrent.futures import ProcessPoolExecutor
from dataclasses import replace
from typing import Final

from .base_names import BASE_CATEGORIES, BASE_NAMES, BASE_NAMES_EN
from .base_objects import BASE_OBJECTS
from .map_data import GameObject, GameObjectFieldEvidence
from .object_candidates import ObjectCandidate, ObjectFieldValue, ObjectSourceKind
from .object_field_selection import (
    build_selection_index,
    object_field_source_priority,
    public_object_field_key,
    select_current_icon_fields,
    select_object_field,
    selected_display_value,
)

BaseObjectTable = Mapping[str, tuple[str, Sequence[tuple[str, str]]]]

# 物化结果按表对象缓存：模块常量表（BASE_OBJECTS）自动缓存；生命周期稳定的
# 合并表（如同一客户端快照的 memo 结果）可显式注册。普通 dict 不支持弱引用，
# 因此用 强引用槽位 + 上限 控制驻留：未注册的临时表一律不缓存，跨运行零增长。
_MAX_CACHED_TABLES: Final = 2
_table_cache_refs: dict[int, BaseObjectTable] = {}
_table_caches: dict[
    int, dict[tuple[tuple[str, str], tuple[ObjectCandidate, ...]], GameObject]
] = {}
_named_candidates_cache: dict[int, tuple[ObjectCandidate, ...]] = {}


def register_base_table_for_caching(table: BaseObjectTable) -> None:
    """注册一个生命周期稳定的表，使其物化结果可跨调用缓存（上限内）。"""
    table_id = id(table)
    if _table_cache_refs.get(table_id) is table:
        return
    if len(_table_cache_refs) >= _MAX_CACHED_TABLES:
        for victim in [
            key
            for key, table_ref in _table_cache_refs.items()
            if table_ref is not BASE_OBJECTS
        ]:
            if len(_table_cache_refs) < _MAX_CACHED_TABLES:
                break
            _table_cache_refs.pop(victim, None)
            _table_caches.pop(victim, None)
            _named_candidates_cache.pop(victim, None)
        if len(_table_cache_refs) >= _MAX_CACHED_TABLES:
            return
    _table_cache_refs[table_id] = table


def _table_is_cached(base_objects: BaseObjectTable) -> bool:
    table_id = id(base_objects)
    if _table_cache_refs.get(table_id) is base_objects:
        return True
    if base_objects is BASE_OBJECTS:
        register_base_table_for_caching(base_objects)
        return True
    return False


_EXT_RANK: Final[Mapping[str, int]] = {
    "base": 0,
    "slk": 10,
    "txt": 20,
    "w3u": 30,
    "w3t": 30,
    "w3a": 30,
    "w3q": 30,
    "w3b": 30,
    "w3d": 30,
    "w3h": 30,
}


def build_object_index(objects: Iterable[GameObject]) -> dict[str, GameObject]:
    """Index only final object ids, never custom-object base aliases."""
    index: dict[str, GameObject] = {}
    for item in objects:
        _ = index.setdefault(item.obj_id, item)
    return index


def build_object_identity_index(
    objects: Iterable[GameObject],
) -> dict[tuple[str, str], GameObject]:
    """Index final objects by exact category and rawcode identity."""
    index: dict[tuple[str, str], GameObject] = {}
    for item in objects:
        _ = index.setdefault((item.category, item.obj_id), item)
    return index


def merge_object_candidates(
    candidates: Iterable[ObjectCandidate],
    base_objects: BaseObjectTable,
) -> tuple[GameObject, ...]:
    """Merge every candidate by category and object id in deterministic order.

    命中缓存的组返回浅拷贝（GameObject 是可变构建器，图标装配/战役改名
    会改属性），缓存主对象永不外发；字段列表共享但全库无原地修改。
    """
    grouped: dict[tuple[str, str], list[ObjectCandidate]] = {}
    for candidate in candidates:
        grouped.setdefault((candidate.category, candidate.obj_id), []).append(candidate)
    keys = sorted(
        grouped,
        key=lambda item: (item[0].casefold(), item[1].encode("latin-1", "replace")),
    )
    # 多核物化：_materialize 是纯函数，进程池结果与串行一致；失败回退串行。
    workers = _configured_workers()
    if workers > 1 and len(keys) >= 64:
        parallel = _merge_parallel(keys, grouped, base_objects, workers)
        if parallel is not None:
            return parallel
    table_id = id(base_objects)
    table_cache = None
    if _table_is_cached(base_objects):
        table_cache = _table_caches.get(table_id)
        if table_cache is None:
            table_cache = {}
            _table_caches[table_id] = table_cache
    results: list[GameObject] = []
    for key in keys:
        group = tuple(grouped[key])
        cache_key = (key, group)
        cached = None if table_cache is None else table_cache.get(cache_key)
        if cached is None:
            cached = _materialize(key, group, base_objects)
            if table_cache is not None:
                table_cache[cache_key] = cached
        results.append(replace(cached))
    return tuple(results)


# 工作进程初始化时注入的基础表（仅并行路径使用；小写以免被当作常量）。
_worker_base_table: BaseObjectTable | None = None


def _configured_workers() -> int:
    """W3XRAY_MATERIALIZE_WORKERS 控制并行度（默认 1=串行，上限 32）。"""
    try:
        requested = int(os.environ.get("W3XRAY_MATERIALIZE_WORKERS", "1"))
    except ValueError:
        return 1
    return max(1, min(requested, 32))


def _init_worker(base_objects: BaseObjectTable) -> None:
    """每个工作进程只接收一次基础表，避免逐任务重复序列化。"""
    global _worker_base_table
    _worker_base_table = base_objects


def _materialize_job(
    identity: tuple[str, str],
    candidates: tuple[ObjectCandidate, ...],
) -> GameObject:
    base = _worker_base_table
    if base is None:
        raise RuntimeError("worker base table not initialized")
    return _materialize(identity, candidates, base)


def _merge_parallel(
    keys: list[tuple[str, str]],
    grouped: dict[tuple[str, str], list[ObjectCandidate]],
    base_objects: BaseObjectTable,
    workers: int,
) -> tuple[GameObject, ...] | None:
    """进程池并行物化；任何异常返回 None 由调用方走串行。"""
    jobs = [(key, tuple(grouped[key])) for key in keys]
    chunksize = max(1, len(jobs) // (workers * 4))
    try:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker, initargs=(base_objects,)
        ) as pool:
            merged = list(pool.map(_materialize_job, *zip(*jobs), chunksize=chunksize))
    except Exception:  # noqa: BLE001 - 并行边界，失败回退串行。
        return None
    return tuple(replace(item) for item in merged)


def named_base_candidates(base_objects: BaseObjectTable) -> tuple[ObjectCandidate, ...]:
    """Build displayable candidates for bundled bases that have known names.

    已注册（含模块常量）的表按身份缓存：候选为 frozen 元组，跨调用直接共享；
    临时表每次重建，不驻留。
    """
    table_id = id(base_objects)
    if _table_is_cached(base_objects):
        cached = _named_candidates_cache.get(table_id)
        if cached is not None:
            return cached
    result = _build_named_base_candidates(base_objects)
    if _table_is_cached(base_objects):
        _named_candidates_cache[table_id] = result
    return result


def _build_named_base_candidates(
    base_objects: BaseObjectTable,
) -> tuple[ObjectCandidate, ...]:
    result: list[ObjectCandidate] = []
    for code, (category, fields) in sorted(base_objects.items()):
        name = BASE_NAMES.get(code)
        if not name:
            continue
        values = [
            ObjectFieldValue(
                "display:name", "名称", name, "base names", ObjectSourceKind.BASE
            )
        ]
        values.extend(
            ObjectFieldValue(
                f"base:{label}",
                label,
                str(value),
                f"base:{code}",
                ObjectSourceKind.BASE,
            )
            for label, value in fields
        )
        result.append(
            ObjectCandidate(category, code, code, False, "base", tuple(values), ())
        )
    return tuple(result)


def _materialize(
    identity: tuple[str, str],
    candidates: tuple[ObjectCandidate, ...],
    base_objects: BaseObjectTable,
) -> GameObject:
    category, obj_id = identity
    representative = max(candidates, key=_candidate_identity_rank)
    selected: dict[str, ObjectFieldValue] = {}
    selection_index = build_selection_index()
    evidence_values: list[ObjectFieldValue] = []
    inherited = base_objects.get(representative.base_id)
    if inherited is not None and inherited[0] == category:
        for label, value in inherited[1]:
            base_field = ObjectFieldValue(
                f"base:{label}",
                label,
                str(value),
                f"base:{representative.base_id}",
                ObjectSourceKind.BASE,
            )
            evidence_values.append(base_field)
            select_object_field(selected, base_field, category, selection_index)
    for candidate in candidates:
        for value in candidate.fields:
            evidence_values.append(value)
            select_object_field(selected, value, category, selection_index)
    ordered = tuple(
        sorted(selected.items(), key=lambda item: (item[1].label.casefold(), item[0]))
    )
    fields = [(value.label, value.value) for _identity, value in ordered]
    field_values = {
        public_object_field_key(identity, value): value.value
        for identity, value in ordered
    }
    field_labels = {
        public_object_field_key(identity, value): value.label
        for identity, value in ordered
    }
    field_sources = {
        public_object_field_key(identity, value): value.source
        for identity, value in ordered
    }
    name = selected_display_value(selected, "display:name") or selected_display_value(
        selected, "display:propernames"
    )
    if not name:
        name = (
            BASE_NAMES.get(representative.base_id) or BASE_NAMES.get(obj_id) or obj_id
        )
    name = name.split("\n", 1)[0][:60]
    selected_icon = selected.get("display:icon")
    icon = "" if selected_icon is None else selected_icon.value.split(",", 1)[0].strip()
    icon_evidence = (
        None
        if selected_icon is None
        else _materialized_evidence((selected_icon,), category)[0]
    )
    icon_fields_evidence = _materialized_evidence(
        select_current_icon_fields(evidence_values, category),
        category,
    )
    refs = _merge_refs(candidates)
    # 搜索文本并入英文名与细类（对象浏览/关系工作区可用英文关键字命中）
    en_name = BASE_NAMES_EN.get(representative.base_id) or BASE_NAMES_EN.get(obj_id)
    fine = BASE_CATEGORIES.get(representative.base_id) or BASE_CATEGORIES.get(obj_id)
    search_text = " ".join(
        value
        for value in (
            obj_id,
            representative.base_id,
            name,
            *(value for _label, value in fields),
            en_name,
            *(fine or ()),
        )
        if value
    )
    return GameObject(
        category=category,
        ext=representative.ext,
        obj_id=obj_id,
        base_id=representative.base_id,
        name=name,
        is_custom=any(candidate.is_custom for candidate in candidates),
        fields=fields,
        search_text=search_text,
        icon=icon,
        ref_fields=refs,
        field_values=field_values,
        field_labels=field_labels,
        field_sources=field_sources,
        field_evidence=_materialized_evidence(evidence_values, category),
        icon_field_evidence=icon_evidence,
        icon_fields_evidence=icon_fields_evidence,
    )


def _materialized_evidence(
    values: Iterable[ObjectFieldValue],
    category: str,
) -> tuple[GameObjectFieldEvidence, ...]:
    unique = {
        GameObjectFieldEvidence(
            key=value.key,
            label=value.label,
            value=value.value,
            source=value.source,
            source_priority=object_field_source_priority(value, category),
            value_type=value.value_type,
            raw_value=value.raw_value,
            value_source=value.value_source,
        )
        for value in values
    }
    return tuple(
        sorted(
            unique,
            key=lambda row: (
                row.key.casefold(),
                row.key,
                -row.source_priority,
                row.source.casefold(),
                row.source,
                row.value,
                row.label.casefold(),
                row.label,
                row.value_type.casefold(),
                row.value_type,
                row.raw_value is not None,
                "" if row.raw_value is None else row.raw_value,
                row.value_source.casefold(),
                row.value_source,
            ),
        )
    )


def _candidate_identity_rank(
    candidate: ObjectCandidate,
) -> tuple[int, int, bool, str, str]:
    source_rank = max((int(value.source_kind) for value in candidate.fields), default=0)
    return (
        _EXT_RANK.get(candidate.ext, 20),
        source_rank,
        candidate.base_id != candidate.obj_id,
        candidate.base_id,
        candidate.ext,
    )


def _merge_refs(candidates: tuple[ObjectCandidate, ...]) -> list[tuple[str, list[str]]]:
    edges = {
        (label, code)
        for candidate in candidates
        for label, codes in candidate.refs
        for code in codes
        if code
    }
    grouped: dict[str, list[str]] = {}
    for label, code in sorted(
        edges, key=lambda item: (item[0].casefold(), item[0], item[1])
    ):
        grouped.setdefault(label, []).append(code)
    return [(label, grouped[label]) for label in grouped]
