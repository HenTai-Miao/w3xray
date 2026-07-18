"""One-map-at-a-time icon, description, and completeness extraction."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from time import monotonic_ns
from typing import Protocol, override

from .batch_descriptions import (
    DescriptionRecord,
    audit_object_descriptions,
)
from .batch_icon_export import (
    IconExportRecord,
)
from .batch_dependencies import fingerprint_dependencies
from .batch_map_icons import export_map_icons
from .batch_item_reports import BatchItemReports, build_batch_item_reports
from .batch_map_manifest import finalize_map_manifest
from .batch_map_result import build_map_result
from .batch_map_publication import (
    MapPublicationStage,
    create_map_stage,
    discard_map_stage,
    map_output_relative,
    publish_map_stage,
)
from .batch_models import MapBatchResult, SourceFingerprint
from .batch_reports import (
    derive_map_state,
    format_description_completeness,
    format_description_tsv,
    format_icon_index_tsv,
    format_map_summary,
)
from .extraction_ledger import BlockState
from .game_data_source import GameDataSource, open_game_data_source
from .icon_evidence_exports import format_icon_integrity, format_unresolved_icon_tsv
from .icon_evidence_index import IconEvidenceIndex
from .load_context import MapLoadContext
from .map_loader import load_map
from .safe_output import write_text_safely
from .safe_output_models import SafeWriteStatus


class BatchProcessingOptions(Protocol):
    @property
    def output_root(self) -> str: ...

    @property
    def game_data_path(self) -> str | None: ...


@dataclass(frozen=True, slots=True)
class BatchMapProcessingError(OSError):
    artifact: str
    detail: str

    @override
    def __str__(self) -> str:
        return f"cannot write {self.artifact}: {self.detail}"


def process_one_map(
    index: int,
    fingerprint: SourceFingerprint,
    options: BatchProcessingOptions,
    context: MapLoadContext,
) -> MapBatchResult:
    """Load, stream-export, report, and atomically publish one source."""
    started = monotonic_ns()
    root = load_map(fingerprint.path, load_context=context)
    publication: MapPublicationStage | None = None
    game_source: GameDataSource | None = None
    try:
        game_source = open_game_data_source(options.game_data_path)
        relative = map_output_relative(index, root.name, fingerprint.sha256)
        publication = create_map_stage(
            options.output_root,
            relative,
            fingerprint.sha256,
        )
        stage = publication.stage
        item_reports = build_batch_item_reports(root)
        maps = item_reports.maps
        descriptions = audit_object_descriptions(item_reports.objects)
        icon_evidence = export_map_icons(root, maps, stage, game_source)
        icons = icon_evidence.exports
        icon_index = icon_evidence.index
        ledgers = tuple(
            item.extraction_ledger for item in maps if item.extraction_ledger
        )
        restricted = sum(
            ledger.count(BlockState.ENCRYPTED_BLOCKED) for ledger in ledgers
        )
        ledger_incomplete = (
            any(
                ledger.count(BlockState.RAW_ONLY) or ledger.count(BlockState.DAMAGED)
                for ledger in ledgers
            )
            or root.extraction_ledger is None
        )
        state = derive_map_state(
            structural_error=False,
            restricted_block_count=restricted,
            ledger_incomplete=ledger_incomplete
            or bool(icon_index.unresolved)
            or bool(icon_index.anonymous_read_failure_count),
            text_incomplete=bool(item_reports.text_incomplete_count),
            relation_incomplete=bool(item_reports.relation_incomplete_count),
            icons=icons,
            descriptions=descriptions,
        )
        elapsed_ms = max(0, (monotonic_ns() - started) // 1_000_000)
        dependency = fingerprint_dependencies(
            fingerprint,
            options,
            context.description_cache_manifest_sha256,
        )
        result = build_map_result(
            fingerprint,
            root.name,
            relative,
            state,
            descriptions,
            icons,
            icon_index,
            restricted,
            elapsed_ms,
            item_reports,
            dependency,
        )
        _write_reports(
            stage,
            result,
            icons,
            descriptions,
            icon_index,
            item_reports,
        )
        result = finalize_map_manifest(stage, result, publication.transaction_id)
        _ = publish_map_stage(publication, options.output_root, result.manifest_sha256)
        publication = None
        return result
    finally:
        discard_map_stage(publication, options.output_root)
        if game_source is not None:
            game_source.close()
        root.close()


def _write_reports(
    stage: Path,
    result: MapBatchResult,
    icons: tuple[IconExportRecord, ...],
    descriptions: tuple[DescriptionRecord, ...],
    icon_index: IconEvidenceIndex,
    item_reports: BatchItemReports,
) -> None:
    reports = (
        ("地图摘要.txt", format_map_summary(result)),
        ("图标索引.tsv", format_icon_index_tsv(icons)),
        ("图标未解析.tsv", format_unresolved_icon_tsv(icon_index)),
        ("对象描述.tsv", format_description_tsv(descriptions)),
        (
            "图标完整性.txt",
            format_icon_integrity(icon_index, icons),
        ),
        ("描述完整性.txt", format_description_completeness(descriptions)),
        *item_reports.artifacts(),
    )
    for name, text in reports:
        write = write_text_safely(str(stage), name, text)
        if write.status is not SafeWriteStatus.WRITTEN:
            raise BatchMapProcessingError(name, write.error or write.status.value)
