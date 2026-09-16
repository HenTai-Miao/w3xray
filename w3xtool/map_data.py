"""Public mutable map-extraction models."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from .external_listfile import ExternalListfileReport
from .icon_evidence_index import IconEvidenceIndex, empty_icon_evidence_index
from .item_relation_models import ItemRelationIndex, empty_item_relation_index
from .object_text_models import ObjectTextIndex, empty_object_text_index

if TYPE_CHECKING:
    from .archive_source import ArchiveSource
    from .doo import Doodad, Unit
    from .extraction_diagnostics import ExtractionDiagnostic
    from .extraction_ledger import ExtractionLedger
    from .gameconfig import NamedGameConfiguration
    from .imp import ImportSummary
    from .mmp import PreviewIconSummary
    from .w3f import W3fInfo
    from .w3i import W3iInfo
    from .w3world import Camera, Region, Sound
    from .wtg_models import TriggerTreeSummary


@dataclass(frozen=True, slots=True)
class GameObjectFieldEvidence:
    """One immutable source value retained before public-field selection."""

    key: str
    label: str
    value: str
    source: str
    source_priority: int
    value_type: str = ""
    raw_value: str | None = None
    value_source: str = ""

    @property
    def source_value(self) -> str:
        """Return the unexpanded source value when collection retained it."""
        return self.value if self.raw_value is None else self.raw_value


@dataclass(slots=True)  # noqa: MUTABLE_OK
class GameObject:
    """Mutable object builder populated by the extraction pipeline."""

    category: str
    ext: str
    obj_id: str
    base_id: str
    name: str
    is_custom: bool
    fields: list[tuple[str, str]] = field(default_factory=list)
    search_text: str = ""
    icon: str = ""
    ref_fields: list[tuple[str, list[str]]] = field(default_factory=list)
    field_values: dict[str, str] = field(default_factory=dict)
    field_sources: dict[str, str] = field(default_factory=dict)
    field_labels: dict[str, str] = field(default_factory=dict)
    field_evidence: tuple[GameObjectFieldEvidence, ...] = ()
    icon_field_evidence: GameObjectFieldEvidence | None = None
    icon_fields_evidence: tuple[GameObjectFieldEvidence, ...] = ()

    @property
    def decimal(self) -> int:
        """Return the four-character object code as a big-endian integer."""
        value = self.obj_id.encode("latin-1", "ignore")[:4].ljust(4, b"\x00")
        return int.from_bytes(value, "big")


@dataclass(slots=True)  # noqa: MUTABLE_OK
class MapData:
    """Mutable map builder preserving the original public extraction fields.

    Extraction incrementally populates this model, so mutability is intentional.
    New lifecycle fields are appended to preserve legacy positional construction.
    """

    path: str
    name: str
    objects: dict[str, list[GameObject]] = field(default_factory=dict)
    scripts: dict[str, str] = field(default_factory=dict)
    all_files: list[str] = field(default_factory=list)
    external_listfile: ExternalListfileReport | None = None
    sub_maps: list[MapData] = field(default_factory=list)
    obj_index: dict[str, GameObject] = field(default_factory=dict)
    doodads: list[Doodad] = field(default_factory=list)
    units: list[Unit] = field(default_factory=list)
    regions: list[Region] = field(default_factory=list)
    cameras: list[Camera] = field(default_factory=list)
    sounds: list[Sound] = field(default_factory=list)
    game_configs: list[NamedGameConfiguration] = field(default_factory=list)
    trigger_summary: TriggerTreeSummary | None = None
    preview_icons: PreviewIconSummary | None = None
    import_summary: ImportSummary | None = None
    w3i: W3iInfo | None = None
    w3f: W3fInfo | None = None
    references: dict[str, list[tuple[str, list[tuple[str, str | None]]]]] = field(
        default_factory=dict
    )
    referenced_by: dict[str, list[tuple[str, str, str]]] = field(default_factory=dict)
    orphans: list[GameObject] = field(default_factory=list)
    ref_low_coverage: bool = False
    script_features: list[str] = field(default_factory=list)
    author_bundle_files: tuple[str, ...] = ()
    archive_source: ArchiveSource | None = None
    diagnostics: list[ExtractionDiagnostic] = field(default_factory=list)
    diagnostic_keys: set[ExtractionDiagnostic] = field(
        default_factory=set, init=False, repr=False
    )
    ui_strings: dict[int, str] | None = None
    object_source_counts: dict[str, int] = field(default_factory=dict)
    extraction_ledger: ExtractionLedger | None = None
    object_texts: ObjectTextIndex = field(default_factory=empty_object_text_index)
    item_relations: ItemRelationIndex = field(default_factory=empty_item_relation_index)
    obj_identity_index: dict[tuple[str, str], GameObject] = field(default_factory=dict)
    icon_evidence: IconEvidenceIndex = field(default_factory=empty_icon_evidence_index)
    _closed: bool = field(default=False, init=False, repr=False)
    # 脚本在加载完成后不再变化；函数范围索引是纯派生数据（实际类型
    # ScriptFunctionIndex，用 object 注解避免与 script_function_index 成环），
    # 多个扫描器（触发器注册/参数索引/局部变量等）共用一次构建结果。
    _script_function_index_cache: object | None = field(
        default=None, init=False, repr=False
    )
    # 资源引用报告同样是加载后不变的派生数据（实际类型 ResourceReport），
    # 分析页、审计、资料包会各自构建一次，共用缓存。
    _resource_report_cache: object | None = field(
        default=None, init=False, repr=False
    )
    # 脚本调用目录（ScriptCallCatalog）与存档分析报告（SaveReport）
    # 也是加载后不变的派生数据；多个索引导出/分析页会重复构建。
    _script_call_catalog_cache: object | None = field(
        default=None, init=False, repr=False
    )
    _save_report_cache: object | None = field(
        default=None, init=False, repr=False
    )

    def category_counts(self) -> dict[str, int]:
        """Return object counts by category in insertion order."""
        return {category: len(items) for category, items in self.objects.items()}

    def close(self) -> None:
        """Close this map's source and recursively close embedded maps once."""
        if self._closed:
            return
        self._closed = True
        try:
            if self.archive_source is not None:
                self.archive_source.close()
        finally:
            for sub_map in self.sub_maps:
                sub_map.close()
