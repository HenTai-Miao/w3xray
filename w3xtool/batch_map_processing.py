"""One-map-at-a-time icon, description, and completeness extraction."""

from __future__ import annotations

from contextlib import ExitStack
from dataclasses import dataclass, replace
from pathlib import Path
from time import monotonic_ns
from typing import Protocol, override

from .batch_descriptions import (
    DescriptionRecord,
    DescriptionState,
    audit_object_descriptions,
)
from .batch_icon_export import (
    IconExportRecord,
    IconExportState,
    IconKind,
    export_anonymous_icon,
    export_named_icon,
)
from .batch_map_publication import (
    create_map_stage,
    discard_map_stage,
    map_output_relative,
    publish_map_stage,
)
from .batch_models import MapBatchResult, MapBatchState, SourceFingerprint
from .batch_reports import (
    derive_map_state,
    description_state_counts,
    format_description_completeness,
    format_description_tsv,
    format_icon_completeness,
    format_icon_index_tsv,
    format_map_summary,
)
from .campaign_sources import open_map_source
from .extraction_ledger import BlockState, ExtractionLedger
from .game_data_source import GameDataSource, open_game_data_source
from .icon_resources import (
    AnonymousIconArchive,
    IconObjectReference,
    collect_icon_references,
    iter_anonymous_blps,
    resolve_named_icon,
)
from .load_context import MapLoadContext
from .map_data import GameObject, MapData
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
    stage: Path | None = None
    game_source: GameDataSource | None = None
    try:
        game_source = open_game_data_source(options.game_data_path)
        stage = create_map_stage(options.output_root)
        descriptions = audit_object_descriptions(_all_objects(root))
        icons, unresolved, anonymous_failures = _export_icons(root, stage, game_source)
        ledgers = tuple(
            item.extraction_ledger for item in _all_maps(root) if item.extraction_ledger
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
            or bool(unresolved)
            or bool(anonymous_failures),
            icons=icons,
            descriptions=descriptions,
        )
        relative = map_output_relative(index, root.name, fingerprint.sha256)
        elapsed_ms = max(0, (monotonic_ns() - started) // 1_000_000)
        result = _map_result(
            fingerprint,
            root.name,
            relative,
            state,
            descriptions,
            icons,
            unresolved,
            anonymous_failures,
            restricted,
            elapsed_ms,
        )
        _write_reports(
            stage,
            result,
            icons,
            descriptions,
            unresolved,
            restricted,
            fingerprint.sha256,
        )
        _ = publish_map_stage(stage, options.output_root, relative, fingerprint.sha256)
        stage = None
        return result
    finally:
        discard_map_stage(stage, options.output_root)
        if game_source is not None:
            game_source.close()
        root.close()


def _export_icons(
    root: MapData,
    stage: Path,
    game_source: GameDataSource | None,
) -> tuple[tuple[IconExportRecord, ...], int, int]:
    records: list[IconExportRecord] = []
    named_indexes: dict[tuple[str, str], int] = {}
    unresolved: set[str] = set()
    anonymous_failures = 0
    maps = _all_maps(root)
    with ExitStack() as stack:
        opened = tuple(
            (item, stack.enter_context(open_map_source(item))) for item in maps
        )
        root_archive = opened[0][1]
        for item, archive in opened:
            sources = (archive,) if item is root else (archive, root_archive)
            for reference in collect_icon_references(_map_objects(item)):
                resource = resolve_named_icon(reference, sources, game_source)
                if resource is None:
                    unresolved.add(reference.normalized_path.casefold())
                    continue
                key = (resource.normalized_path.casefold(), resource.sha256)
                previous = named_indexes.get(key)
                if previous is None:
                    named_indexes[key] = len(records)
                    records.append(export_named_icon(str(stage), resource))
                else:
                    current = records[previous]
                    merged = tuple(
                        sorted(
                            set((*current.objects, *resource.objects)),
                            key=_reference_key,
                        )
                    )
                    records[previous] = replace(current, objects=merged)
            ledger = item.extraction_ledger
            if ledger is None:
                continue
            expected = _anonymous_blp_count(ledger)
            if not isinstance(archive, AnonymousIconArchive):
                anonymous_failures += expected
                continue
            exported = 0
            for resource in iter_anonymous_blps(archive, ledger):
                records.append(export_anonymous_icon(str(stage), resource))
                exported += 1
            anonymous_failures += max(0, expected - exported)
    return tuple(records), len(unresolved), anonymous_failures


def _map_result(
    fingerprint: SourceFingerprint,
    display_name: str,
    relative: str,
    state: MapBatchState,
    descriptions: tuple[DescriptionRecord, ...],
    icons: tuple[IconExportRecord, ...],
    unresolved: int,
    anonymous_failures: int,
    restricted: int,
    elapsed_ms: int,
) -> MapBatchResult:
    first_error = next((item.error for item in icons if item.error), "")
    if not first_error and unresolved:
        first_error = f"unresolved named icons: {unresolved}"
    if not first_error and anonymous_failures:
        first_error = f"anonymous BLP read failures: {anonymous_failures}"
    missing = sum(
        item.state is DescriptionState.SOURCE_MISSING for item in descriptions
    )
    if not first_error and missing:
        first_error = f"missing descriptions: {missing}"
    return MapBatchResult(
        source=fingerprint,
        display_name=display_name,
        output_directory=relative,
        stage="published",
        state=state,
        first_error=first_error,
        object_count=len({(item.category, item.object_id) for item in descriptions}),
        description_counts=description_state_counts(descriptions),
        named_icon_count=sum(item.kind is IconKind.NAMED for item in icons),
        anonymous_icon_count=sum(item.kind is IconKind.ANONYMOUS for item in icons),
        original_written_count=sum(item.original_written for item in icons),
        png_written_count=sum(item.png_written for item in icons),
        icon_failure_count=(
            unresolved
            + anonymous_failures
            + sum(item.state is not IconExportState.COMPLETE for item in icons)
        ),
        restricted_block_count=restricted,
        elapsed_ms=elapsed_ms,
    )


def _write_reports(
    stage: Path,
    result: MapBatchResult,
    icons: tuple[IconExportRecord, ...],
    descriptions: tuple[DescriptionRecord, ...],
    unresolved: int,
    restricted: int,
    digest: str,
) -> None:
    reports = (
        ("地图摘要.txt", format_map_summary(result)),
        ("图标索引.tsv", format_icon_index_tsv(icons)),
        ("对象描述.tsv", format_description_tsv(descriptions)),
        (
            "图标完整性.txt",
            format_icon_completeness(
                icons,
                unresolved_named_count=unresolved,
                restricted_block_count=restricted,
            ),
        ),
        ("描述完整性.txt", format_description_completeness(descriptions)),
        (".w3xray-batch-owned", digest),
    )
    for name, text in reports:
        write = write_text_safely(str(stage), name, text)
        if write.status is not SafeWriteStatus.WRITTEN:
            raise BatchMapProcessingError(name, write.error or write.status.value)


def _all_maps(root: MapData) -> tuple[MapData, ...]:
    return (
        (root, *(child for item in (root, *root.sub_maps) for child in item.sub_maps))
        if root.sub_maps
        else (root,)
    )


def _map_objects(item: MapData) -> tuple[GameObject, ...]:
    return tuple(obj for values in item.objects.values() for obj in values)


def _all_objects(root: MapData) -> tuple[GameObject, ...]:
    return tuple(obj for item in _all_maps(root) for obj in _map_objects(item))


def _anonymous_blp_count(ledger: ExtractionLedger) -> int:
    return sum(
        entry.block_index is not None
        and entry.internal_path.replace("\\", "/").casefold().startswith("unknown/")
        and entry.internal_path.casefold().endswith(".blp")
        for entry in ledger.entries
    )


def _reference_key(item: IconObjectReference) -> tuple[str, str, str]:
    return item.category.casefold(), item.object_id, item.object_name
