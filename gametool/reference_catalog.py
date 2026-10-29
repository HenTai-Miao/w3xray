"""Complete offline reference over existing project assets and optional map packs.

Definitions describe static source evidence. They are neither runtime getters nor
an assertion that a base object exists in the caller's current map or build.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import replace
import hashlib
import json
from pathlib import Path

from . import base_names, base_objects, field_meta, fields, live_handle_chain
from .local_id_tables import LocalIdTablePath, LocalIdTableSources
from .map_reference_sources import (
    CancelCheck,
    MapReferenceSources,
    ProgressCallback,
    check_cancelled,
)
from .map_reference_tables import bind_map_record
from .map_reference_identity import MapObjectIdentity
from .map_reference_records import resolve_scope_records
from .object_codes import valid_object_code
from .live_profile_validation import (
    ProfileSupport,
    architecture_pointer_size,
    inspect_profile_support,
    validate_profile_data,
)
from .pack_query_object_details import ObjectRecord, load_object_catalog
from .pack_query_objects import OBJECT_TABLES, object_category
from .pack_query_options import query_limit_error
from .reference_models import (
    ReferenceCatalog,
    ReferenceRecord,
    ReferenceSearchResult,
    ReferenceSource,
    ReferenceValue,
)
from .reference_sources import PackReferenceSources, reference_pack_scopes
from .search import compile_query

_BUILTIN_OBJECTS = "builtin:base_objects"
_BUILTIN_NAMES = "builtin:base_names"
_FIELD_META = "builtin:field_meta"
_FIELD_LABELS = "builtin:fields"
_PROFILES = "builtin:live_profiles"
_UNKNOWN_BUILD = "unrecorded"
_LOADED_SOURCE_BASELINES: dict[str, tuple[str, str, str]] = {}


def _unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(value for value in values if value))


def _builtin_sources() -> tuple[tuple[ReferenceSource, ...], tuple[str, ...]]:
    definitions = (
        (
            _BUILTIN_OBJECTS,
            base_objects.__file__,
            base_objects.BASE_OBJECTS,
            "项目既有生成表；build_base_names.py 从游戏 *Data.slk 生成，源游戏 build 未记录。",
        ),
        (
            _BUILTIN_NAMES,
            base_names.__file__,
            {
                "names": base_names.BASE_NAMES,
                "english": base_names.BASE_NAMES_EN,
                "categories": base_names.BASE_CATEGORIES,
            },
            "项目既有中文名称表；英文/细类由 build_base_catalog.py 合并 MIT 来源 "
            "flowtsohg/war3-objectdata@dc5e2da21217dba8e5f750c1e867d691ab193ec1；"
            "此提交是来源身份，不是游戏 build。",
        ),
        (
            _FIELD_META,
            field_meta.__file__,
            {
                "labels": field_meta.GENERATED_FIELD_LABELS,
                "types": field_meta.FIELD_TYPES,
                "applicability": field_meta.GENERATED_FIELD_APPLICABILITY,
                "bounds": field_meta.GENERATED_FIELD_BOUNDS,
                "constants": field_meta.GENERATED_FIELD_CONSTANTS,
                "categories": field_meta.GENERATED_FIELD_CATEGORIES,
                "category_provenance": field_meta.GENERATED_FIELD_CATEGORY_PROVENANCE,
                "source_manifest": field_meta.GENERATED_FIELD_SOURCE_MANIFEST,
                "field_provenance": field_meta.GENERATED_FIELD_PROVENANCE,
                "source_differences": field_meta.GENERATED_FIELD_SOURCE_DIFFERENCES,
            },
            "build_field_labels.py 生成的静态字段定义；历史 seed 的游戏 build 未记录，"
            "版本化参考仅补缺并保留显式类别，fields.py 人工标签优先。"
            "完整生成输入台账（上游文件 hash 为参考来源声明）："
            + json.dumps(
                field_meta.GENERATED_FIELD_SOURCE_MANIFEST,
                ensure_ascii=False,
                sort_keys=True,
            ),
        ),
        (
            _FIELD_LABELS,
            fields.__file__,
            {"labels": fields.FIELD_LABELS, "name_fields": fields.NAME_FIELD},
            "项目 fields.py 精选字段标签与名称字段角色；完整生成标签作为别名保留。",
        ),
        (
            _PROFILES,
            live_handle_chain.__file__,
            {
                "build_profiles": {
                    version: live_handle_chain.profile_to_dict(profile)
                    for version, profile in live_handle_chain.build_profiles().items()
                },
                "family_templates": (
                    live_handle_chain.profile_to_dict(
                        live_handle_chain.resolve_profile(None)
                    ),
                    live_handle_chain.profile_to_dict(
                        live_handle_chain.resolve_profile(None, "reforged", "x64")
                    ),
                ),
            },
            "项目现有只读 build_profiles/resolve_profile 纯数据；"
            "每个档案保留自己的精确版本、来源及验证档位。",
        ),
    )
    sources: list[ReferenceSource] = []
    diagnostics: list[str] = []
    for source_id, path, data, provenance in definitions:
        # This fingerprint always binds the values used by the catalog, even
        # when a .py file has changed since this process imported its module.
        payload = json.dumps(
            data, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        observed_file_hash = ""
        file_state = "observed-unbound"
        try:
            observed_file_hash = hashlib.sha256(Path(path).read_bytes()).hexdigest()
        except FileNotFoundError:
            file_state = "no-independent-file"
        except OSError as exc:
            file_state = "unreadable"
            diagnostics.append(
                f"{path}: 无法独立观测磁盘源码指纹: {exc}；加载数据指纹仍保留。"
            )
        baseline = _LOADED_SOURCE_BASELINES.get(source_id)
        identity = (str(path), digest)
        if baseline is None or baseline[:2] != identity:
            _LOADED_SOURCE_BASELINES[source_id] = (*identity, observed_file_hash)
        elif baseline[2] != observed_file_hash:
            file_state = (
                "changed-since-loaded-data"
                if observed_file_hash
                else "missing-since-loaded-data"
            )
            diagnostics.append(
                f"{path}: 同一已加载数据指纹下磁盘源码已变化或不可读取；保留本进程已加载证据，"
                "未将磁盘新源码的 SHA-256 绑定到旧值。重启程序以载入新定义。"
            )
        if file_state == "no-independent-file":
            provenance += " 当前没有独立源文件（兼容内嵌/PYZ 资源）；主指纹仍覆盖完整加载数据的规范 JSON。"
        provenance += (
            " 主 SHA-256 绑定本进程完整加载数据；磁盘源码指纹为独立观测，"
            "未证明其版本与已加载数据一致。"
        )
        sources.append(
            ReferenceSource(
                source_id,
                str(Path(path).resolve()),
                digest,
                provenance,
                fingerprint_basis="canonical-json-data",
                source_file_sha256=observed_file_hash,
                source_file_state=file_state,
            )
        )
    return tuple(sources), tuple(diagnostics)


def _verify_builtin_sources(sources: Iterable[ReferenceSource]) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for source in sources:
        if not source.source_file_sha256:
            continue
        try:
            if (
                hashlib.sha256(Path(source.path).read_bytes()).hexdigest()
                == source.source_file_sha256
            ):
                continue
        except OSError:
            pass
        diagnostics.append(
            f"{source.path}: 磁盘源码的独立观测在交付前变化；加载数据主指纹不变，"
            "未把新源码归因给已有值，请重启后刷新。"
        )
    return tuple(diagnostics)


def _field_aliases(key: str, recorded_label: str = "") -> tuple[str, ...]:
    return _unique(
        (
            recorded_label,
            fields.label_for(key),
            field_meta.GENERATED_FIELD_LABELS.get(key, ""),
            field_meta.GENERATED_FIELD_CONSTANTS.get(key, ""),
        )
    )


def _base_records() -> dict[tuple[str, str], ReferenceRecord]:
    records: dict[tuple[str, str], ReferenceRecord] = {}
    for code, (declared, values) in base_objects.BASE_OBJECTS.items():
        category = object_category(declared)
        if not valid_object_code(code):
            continue
        name = base_names.BASE_NAMES.get(code, code)
        fine = base_names.BASE_CATEGORIES.get(code, ("", ""))
        aliases = _unique((base_names.BASE_NAMES_EN.get(code, ""), *fine))
        records[(category, code)] = ReferenceRecord(
            "objects",
            code,
            name,
            category,
            aliases=aliases,
            sources=(_BUILTIN_OBJECTS, _BUILTIN_NAMES),
            values=tuple(
                ReferenceValue(
                    key,
                    fields.label_for(key),
                    value,
                    fields.field_type(key),
                    _BUILTIN_OBJECTS,
                    "BASE_OBJECTS 的原始键/值；标签键未反推为四码字段。",
                    aliases=_field_aliases(key),
                    category=category,
                    object_id=code,
                )
                for key, value in values
            ),
            details=(
                ("基础ID", code),
                ("说明", "静态基础目录；当前地图可用性与源游戏 build 未记录。"),
            ),
        )
    declared_codes = set(base_objects.BASE_OBJECTS)
    name_codes = (
        set(base_names.BASE_NAMES)
        | set(base_names.BASE_NAMES_EN)
        | set(base_names.BASE_CATEGORIES)
    )
    for code in sorted(name_codes - declared_codes):
        if not valid_object_code(code):
            continue
        fine = base_names.BASE_CATEGORIES.get(code, ("", ""))
        records[("", code)] = ReferenceRecord(
            "objects",
            code,
            base_names.BASE_NAMES.get(code)
            or base_names.BASE_NAMES_EN.get(code)
            or code,
            aliases=_unique((base_names.BASE_NAMES_EN.get(code, ""), *fine)),
            sources=(_BUILTIN_NAMES,),
            state="name-only",
            details=(
                ("身份来源", "基础名称/细类表独立记录"),
                (
                    "分类与字段",
                    "对象表未记录类别/字段；保留原始身份，不按四码前缀猜测，也不提供跨类别基础继承。",
                ),
            ),
        )
    return records


def _base_for_record(
    record: ObjectRecord,
    category: str,
    bases: dict[tuple[str, str], ReferenceRecord],
) -> ReferenceRecord | None:
    if record.from_fields:
        return None
    # Only a declared same-category base ID can supply a custom object's base.
    base_id = record.row[3]
    return (
        bases.get((category, base_id))
        if base_id
        else bases.get((category, record.row[1]))
    )


def _map_record(
    pack: Path,
    category: str,
    record: ObjectRecord,
    header: tuple[str, ...],
    bases: dict[tuple[str, str], ReferenceRecord],
) -> ReferenceRecord:
    row = record.row
    code = row[1]
    id_source = str(pack / "对象ID" / f"{category}.tsv")
    field_source = str(pack / "对象字段.tsv")
    base = _base_for_record(record, category, bases)
    values = tuple(
        ReferenceValue(
            field.key,
            field.label or fields.label_for(field.key),
            field.value,
            fields.field_type(field.key),
            field_source,
            field.source,
            (
                "campaign-inherited"
                if dict(field.extras).get("证据角色") == "继承物化字段"
                else "inherited-evidence"
                if field.key.casefold().startswith("base:")
                else "map-evidence"
            )
            if field.confirmed
            else "overridden-campaign"
            if field.state == "overridden"
            and dict(field.extras).get("来源优先级") in {"11", "12"}
            else field.state,
            _field_aliases(field.key, field.label),
            field.extras,
            category,
            code,
        )
        for field in record.evidence.fields
    )
    # Keep all base evidence, but never promote it over an explicit map value.
    # Equal labels matter because BASE_OBJECTS stores many SLK display labels.
    overridden = {
        label
        for field in values
        if field.state == "map-evidence"
        for label in (field.key, field.label, *field.aliases)
    }
    inherited = (
        tuple(
            replace(
                value,
                state="overridden-base"
                if value.key in overridden or value.label in overridden
                else "base-reference",
                object_id=code,
            )
            for value in base.values
        )
        if base is not None
        else ()
    )
    details = (
        (
            "身份来源",
            "仅对象字段确认；基础ID/自定义标记未记录"
            if record.from_fields
            else "对象ID表",
        ),
        ("数值", row[2]),
        ("基础ID", row[3]),
        ("自定义标记", row[5]),
        ("说明", row[6]),
        *(
            (header[index] if index < len(header) else f"扩展字段{index + 1}", value)
            for index, value in enumerate(row[7:], 7)
        ),
    )
    return ReferenceRecord(
        "objects",
        code,
        row[4] or " / ".join(record.evidence.names) or code,
        category,
        str(pack),
        _unique((*record.evidence.names, *(base.aliases if base else ()))),
        sources=_unique(
            (
                id_source if not record.from_fields else "",
                field_source if values else "",
                *(base.sources if base else ()),
            )
        ),
        state="field-only" if record.from_fields else "map-evidence",
        values=(*values, *inherited),
        details=details,
        raw_rows=(row,),
    )


def _metadata_records(
    observations: dict[str, list[ReferenceValue]],
) -> tuple[ReferenceRecord, ...]:
    keys = sorted(
        set(fields.FIELD_LABELS)
        | set(field_meta.GENERATED_FIELD_LABELS)
        | set(field_meta.FIELD_TYPES)
        | set(field_meta.GENERATED_FIELD_APPLICABILITY)
        | set(field_meta.GENERATED_FIELD_BOUNDS)
        | set(field_meta.GENERATED_FIELD_CONSTANTS)
        | set(field_meta.GENERATED_FIELD_CATEGORIES)
        | set(observations)
    )
    records: list[ReferenceRecord] = []
    differences: dict[str, dict[str, dict[str, object]]] = {}
    for source, tables in field_meta.GENERATED_FIELD_SOURCE_DIFFERENCES.items():
        for table, values in tables.items():
            for code, value in values.items():
                differences.setdefault(code, {}).setdefault(source, {})[table] = value
    name_categories = {
        "w3u": "单位",
        "w3t": "物品",
        "w3a": "技能",
        "w3q": "科技",
        "w3b": "可破坏物",
        "w3d": "装饰物",
        "w3h": "增益",
    }
    for key in keys:
        seen = tuple(observations.get(key, ()))
        category_sources = field_meta.GENERATED_FIELD_CATEGORY_PROVENANCE.get(key, {})
        category_builds = _unique(
            str(field_meta.GENERATED_FIELD_SOURCE_MANIFEST[source]["game_build"])
            for sources in category_sources.values()
            for source in sources
            if "game_build"
            in field_meta.GENERATED_FIELD_SOURCE_MANIFEST.get(source, {})
        )
        categories = _unique(
            (
                *(value.category for value in seen),
                *(
                    object_category(category)
                    for category in field_meta.GENERATED_FIELD_CATEGORIES.get(key, ())
                ),
                *(
                    name_categories[ext]
                    for ext, name in fields.NAME_FIELD.items()
                    if name == key
                ),
                "技能" if key in field_meta.GENERATED_FIELD_APPLICABILITY else "",
            )
        )
        applicable, excluded = fields.ability_field_specificity(key)
        bounds = fields.ability_field_bounds(key)
        details = (
            ("字段类型", fields.field_type(key) or "未记录"),
            ("common.j 常量", fields.ability_field_constant(key)),
            ("useSpecific", ",".join(applicable)),
            ("notSpecific", ",".join(excluded)),
            ("minVal", "未记录" if bounds is None or bounds[0] is None else bounds[0]),
            ("maxVal", "未记录" if bounds is None or bounds[1] is None else bounds[1]),
            (
                "类别证据",
                " / ".join(categories) or "元数据未记录；未按字段前缀猜测类别",
            ),
            (
                "版本化类别来源",
                json.dumps(category_sources, ensure_ascii=False, sort_keys=True)
                if category_sources
                else "",
            ),
            (
                "版本化类别范围",
                "类别声明来自列示编辑器版本；标签/类型/边界按历史 seed 补缺与人工优先级保留。"
                if category_sources
                else "",
            ),
            (
                "生成条目来源",
                json.dumps(
                    field_meta.GENERATED_FIELD_PROVENANCE.get(key, {}),
                    ensure_ascii=False,
                    sort_keys=True,
                ),
            ),
            (
                "版本参考差异",
                json.dumps(differences[key], ensure_ascii=False, sort_keys=True)
                if key in differences
                else "",
            ),
            ("语义", "静态字段定义与已导出值证据；不代表运行时 getter 或实时生效。"),
        )
        metadata_sources = (
            *(
                [_FIELD_META]
                if any(
                    key in table
                    for table in (
                        field_meta.GENERATED_FIELD_LABELS,
                        field_meta.FIELD_TYPES,
                        field_meta.GENERATED_FIELD_APPLICABILITY,
                        field_meta.GENERATED_FIELD_BOUNDS,
                        field_meta.GENERATED_FIELD_CONSTANTS,
                        field_meta.GENERATED_FIELD_CATEGORIES,
                    )
                )
                else []
            ),
            *([_FIELD_LABELS] if key in fields.FIELD_LABELS else []),
        )
        records.append(
            ReferenceRecord(
                "fields",
                key,
                fields.label_for(key),
                aliases=_field_aliases(key),
                categories=categories,
                builds=_unique((_UNKNOWN_BUILD, *category_builds)),
                sources=_unique((*metadata_sources, *(value.source for value in seen))),
                values=seen,
                details=details,
            )
        )
    return tuple(records)


def _profile_layout_values(
    coverage: ProfileSupport, source: str
) -> tuple[ReferenceValue, ...]:
    return tuple(
        ReferenceValue(
            f"{layout.scope}.{layout.key}",
            layout.label or layout.key,
            f"offset={layout.offset}"
            if layout.offset is not None
            else "pointer_offsets=" + json.dumps(layout.pointer_offsets),
            layout.value_type,
            source,
            layout.source,
            "declared-layout-only",
            extras=(("档案声明 evidence", layout.evidence),),
        )
        for layout in coverage.fields
    )


def _version_record(profile: live_handle_chain.LiveBuildProfile) -> ReferenceRecord:
    explanations = {
        "exact": "历史精确档案；仅此版本/指纹有既有验证证据，当前进程仍需重新核对。",
        "rva-table": "公开 RVA 表来源；句柄链未获此 build 的真机验证，不等于完整支持。",
        "template": "未收录 Classic 的引擎家族推导模板；没有借用其他版本的确认地址。",
        "reforged-pending": "Reforged x64 只读档案待建立；未确认句柄/单位/字段布局。",
    }
    data = live_handle_chain.profile_to_dict(profile)
    if profile.version:
        coverage = inspect_profile_support(data)
    else:
        # A family template deliberately has no concrete four-part build.
        # Do not feed it to the concrete-profile validator or erase its source
        # identity when that validator correctly requires a game_version.
        coverage = ProfileSupport(
            engine=profile.engine,
            arch=profile.arch,
            tier=profile.tier,
            source=profile.source,
            pointer_size=architecture_pointer_size(profile.arch),
            complete=True,
            diagnostics=(
                "通用引擎家族声明，没有具体 game_version；不是可导入的精确 build 档案。",
                explanations.get(profile.tier, "此模板档位未识别；未声明运行时支持。"),
            ),
        )
    coverage_data = coverage.to_dict()
    coverage_data["declaration_kind"] = (
        "concrete-build" if profile.version else "family-template"
    )
    coverage_data["concrete_build"] = bool(profile.version)

    build = profile.version or (
        "classic-template" if profile.tier == "template" else "reforged-pending"
    )
    return ReferenceRecord(
        "versions",
        build,
        profile.version or build,
        category="版本档案",
        builds=(build,),
        sources=(_PROFILES,),
        state=profile.tier,
        aliases=(profile.engine, profile.arch, profile.tier),
        values=_profile_layout_values(coverage, _PROFILES),
        details=(
            ("engine", profile.engine),
            ("arch", profile.arch),
            ("tier", profile.tier),
            ("来源", profile.source),
            (
                "验证边界",
                explanations.get(profile.tier, "此档位未识别，须核对原档案。"),
            ),
            ("完整档案纯数据", json.dumps(data, ensure_ascii=False, sort_keys=True)),
        ),
        diagnostics=coverage.diagnostics,
        coverage=coverage_data,
    )


def _external_profile(path: Path, adapter: PackReferenceSources) -> ReferenceRecord:
    payload, error = adapter._read(path, path.parent)
    if payload is None:
        raise ValueError(f"{path}: {error}")

    def unique_pairs(pairs: list[tuple[str, object]]) -> dict[str, object]:
        data: dict[str, object] = {}
        for key, value in pairs:
            if key in data:
                raise ValueError(f"档案 JSON 有重复键 {key!r}；未猜测哪项有效。")
            data[key] = value
        return data

    raw = payload.decode("utf-8-sig")
    data = validate_profile_data(json.loads(raw, object_pairs_hook=unique_pairs))
    coverage = inspect_profile_support(data)
    if not coverage.complete:
        raise ValueError("; ".join(coverage.diagnostics))
    source_id = str(path)
    adapter.sources[source_id] = replace(
        adapter.sources[source_id],
        provenance="调用方显式提供的纯数据 JSON 档案；仅验证声明与字段类型，未读取游戏。",
        build=coverage.version,
        state="profile-declaration",
    )
    return ReferenceRecord(
        "versions",
        coverage.version,
        coverage.version,
        category="版本档案",
        scope=source_id,
        aliases=(coverage.engine, coverage.arch, coverage.tier),
        builds=(coverage.version,),
        sources=(source_id,),
        state=coverage.tier,
        values=_profile_layout_values(coverage, source_id),
        details=(
            ("engine", coverage.engine),
            ("arch", coverage.arch),
            ("tier", coverage.tier),
            ("来源", coverage.source),
            ("runtime_verified", "False：未读取进程，档案声明不证明当前游戏的支持。"),
            ("原始 JSON", raw),
        ),
        diagnostics=coverage.diagnostics,
        coverage=coverage.to_dict(),
    )


def load_reference_catalog(
    pack_dir: str | Path | None = None,
    *,
    profile_json: str | Path | None = None,
    id_tables: Iterable[LocalIdTablePath] = (),
    map_path: str | Path | None = None,
    cancelled: CancelCheck | None = None,
    progress: ProgressCallback | None = None,
) -> ReferenceCatalog:
    """Load all committed definitions plus every confirmed optional pack record.

    A new invocation re-reads all pack and external ID-table bytes. External
    labels are appended independently and never supply map/base definitions.
    The field table is parsed once per scope by the shared object catalog loader.
    """
    if pack_dir is not None and map_path is not None:
        raise ValueError(
            "--map 与 --pack 不能同时使用；请选择地图归档或已导出的知识包。"
        )
    check_cancelled(cancelled)
    builtin_sources, source_diagnostics = _builtin_sources()
    sources = list(builtin_sources)
    base = _base_records()
    objects = dict(base)
    extra_objects: list[ReferenceRecord] = []
    observations: dict[str, list[ReferenceValue]] = defaultdict(list)
    diagnostics = list(source_diagnostics)
    roots: tuple[str, ...] = ()
    adapter = PackReferenceSources()
    local_ids = LocalIdTableSources(id_tables)
    map_sources = (
        MapReferenceSources(map_path, cancelled=cancelled, progress=progress)
        if map_path is not None
        else None
    )
    if map_sources is not None:
        scope_objects: dict[str, dict[tuple[str, str], ReferenceRecord]] = {}
        for scope_index, metadata in enumerate(map_sources.scopes):
            scope = Path(metadata.scope)
            if (scope, "对象字段.tsv") not in map_sources.tables:
                continue
            indexes = load_object_catalog(scope, OBJECT_TABLES, map_sources)
            shared_objects = scope_objects.get(metadata.shared_scope, {})
            current_objects = dict(shared_objects)
            current_records: list[ReferenceRecord] = []
            for category, index in indexes.items():
                for record in index.records:
                    check_cancelled(cancelled)
                    current = bind_map_record(
                        _map_record(
                            scope,
                            category,
                            record,
                            index.view.rows[0],
                            base if record.row[3] else {},
                        ),
                        metadata.scope,
                        map_sources.sources,
                        map_sources.members[metadata.scope],
                        map_sources.identities[metadata.scope].get(
                            (category, record.row[1]), MapObjectIdentity()
                        ),
                    )
                    current_records.append(current)
            resolved_records, inheritance_notes = resolve_scope_records(
                tuple(current_records),
                shared_objects,
                base,
            )
            if inheritance_notes:
                map_sources.diagnostics.extend(inheritance_notes)
                map_sources.scopes[scope_index] = replace(
                    metadata,
                    complete=False,
                    diagnostics=(*metadata.diagnostics, *inheritance_notes),
                )
            for current in resolved_records:
                current_objects[(current.category, current.id)] = current
                extra_objects.append(current)
                for value in current.values:
                    if not value.source.startswith("builtin:"):
                        observations[value.key].append(value)
            scope_objects[metadata.scope] = current_objects
    if pack_dir is not None:
        root = Path(pack_dir).absolute()
        scopes, scope_notes = reference_pack_scopes(root)
        diagnostics.extend(scope_notes)
        roots = (str(root),)
        for scope in scopes:
            indexes = load_object_catalog(scope, OBJECT_TABLES, adapter)
            for category, index in indexes.items():
                for record in index.records:
                    current = _map_record(
                        scope, category, record, index.view.rows[0], base
                    )
                    if scope == root:
                        identity = (category, current.id)
                        previous = objects.get(identity)
                        if previous is not None and previous.scope == str(scope):
                            # Duplicate ID rows remain independent evidence, never
                            # silently pick one of competing names/base/custom flags.
                            extra_objects.append(current)
                        else:
                            objects[identity] = current
                    else:
                        extra_objects.append(current)
                    for value in current.values:
                        if value.source == str(scope / "对象字段.tsv"):
                            observations[value.key].append(value)
    versions = tuple(
        _version_record(profile)
        for profile in live_handle_chain.build_profiles().values()
    )
    versions += (
        _version_record(live_handle_chain.resolve_profile(None)),
        _version_record(live_handle_chain.resolve_profile(None, "reforged", "x64")),
    )
    if profile_json is not None:
        versions += (_external_profile(Path(profile_json).absolute(), adapter),)
    for external in local_ids.records:
        previous = objects.get((external.category, external.id))
        if previous is not None and previous.label != external.label:
            external = replace(
                external,
                diagnostics=(
                    *external.diagnostics,
                    f"与 {previous.scope} 的同类别同ID名称 {previous.label!r} 不同；"
                    "外部标签单独保留，未覆盖或继承该对象的任何定义。",
                ),
            )
        extra_objects.append(external)
    records = (
        *objects.values(),
        *extra_objects,
        *_metadata_records(observations),
        *versions,
    )
    adapter.verify()
    diagnostics.extend(_verify_builtin_sources(builtin_sources))
    diagnostics.extend(adapter.diagnostics)
    local_ids.verify()
    diagnostics.extend(local_ids.diagnostics)
    sources.extend(adapter.sources.values())
    sources.extend(local_ids.sources.values())
    if map_sources is not None:
        map_sources.verify()
        diagnostics.extend(map_sources.diagnostics)
        sources.extend(map_sources.sources.values())
    check_cancelled(cancelled)
    return ReferenceCatalog(
        records,
        tuple(sources),
        tuple(diagnostics),
        tuple(dict.fromkeys((*roots, *local_ids.input_roots))),
        map_path=str(map_sources.path) if map_sources is not None else "",
        map_scopes=tuple(map_sources.scopes) if map_sources is not None else (),
        source_counts=tuple(
            (scope.scope, sum(count for _category, count in scope.category_counts))
            for scope in map_sources.scopes
        )
        if map_sources is not None
        else (),
        input_files=(str(map_sources.path),) if map_sources is not None else (),
    )


def search_reference_catalog(
    catalog: ReferenceCatalog,
    query: str = "",
    *,
    kind: str = "all",
    category: str = "",
    build: str = "",
    source: str = "",
    limit: int = 0,
) -> ReferenceSearchResult:
    """Compile once and match independent fields; explicit limits keep records."""
    if error := query_limit_error(limit):
        raise ValueError(error)
    if kind not in {"all", "objects", "fields", "versions"}:
        raise ValueError("kind 需要 all/objects/fields/versions")
    category = object_category(category) if category else ""
    expression = compile_query(query)
    diagnostics = list(
        _unique(
            (
                *catalog.diagnostics,
                *(
                    f"{record.kind} {record.category or '未分类'}:{record.id} "
                    f"[{record.scope}]: {note}"
                    for record in catalog.records
                    if record.kind == "objects"
                    for note in record.diagnostics
                ),
            )
        )
    )
    recovery: list[str] = []
    matches: list[ReferenceRecord] = []
    by_source = {item.id: item for item in catalog.sources}
    source_term = source.casefold()
    for record in catalog.records:
        if kind != "all" and record.kind != kind:
            continue
        if (
            category
            and category != record.category
            and category not in record.categories
        ):
            continue
        if build and build not in record.builds:
            continue
        if source_term:
            source_fields = [record.scope, *record.sources]
            source_fields.extend(value.provenance for value in record.values)
            source_fields.extend(value.source for value in record.values)
            source_fields.extend(
                value for label, value in record.details if label == "来源"
            )
            for key in record.sources:
                if item := by_source.get(key):
                    source_fields.extend((item.path, item.provenance, item.sha256))
            if not any(source_term in value.casefold() for value in source_fields):
                continue
        if query.strip() and expression.is_empty:
            continue
        if expression.score_fields(record.search_fields()) is not None:
            matches.append(record)
    known_builds = {value for record in catalog.records for value in record.builds}
    if build and build not in known_builds:
        recovery.append(
            f"未记录 build {build}；可用 --kind versions 列出精确档案与模板。"
            "基础/地图定义的 build=unrecorded，不能据此宣称适用于该版本。"
        )
    if query.strip() and expression.is_empty:
        recovery.append(
            '查询表达式没有关键词；可输入字段/四码，或使用 &&、||、%、括号与 ="精准词"。'
        )
    if not matches:
        recovery.extend(
            (
                f"本地目录共有 {len(catalog.records)} 条已确认静态记录；请清空关键词或筛选条件看全量。",
                "可用 --kind fields 查字段、--kind versions 查验证范围，或 --map PATH / --pack DIR 叠加地图证据。",
            )
        )
    selected = matches[:limit] if limit else matches
    return ReferenceSearchResult(
        tuple(selected),
        catalog.sources,
        tuple(diagnostics),
        len(catalog.records),
        len(matches),
        len(matches) - len(selected),
        query,
        kind,
        category,
        build,
        source,
        limit,
        catalog.complete,
        tuple(recovery),
        catalog.input_roots,
        catalog.map_path,
        catalog.map_scopes,
        catalog.source_counts,
        catalog.input_files,
    )
