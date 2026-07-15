"""Build one strict immutable icon evidence index for a logical map."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, assert_never, override

from .game_data_source import GameDataSource
from .icon_evidence_index import IconEvidenceIndex
from .icon_evidence_models import (
    FilteredIconEvidence,
    IconArchiveLayer,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from .icon_field_evidence import IconFieldDisposition, classify_icon_field
from .icon_path_evidence import plan_icon_path
from .icon_reference_resolution import resolve_icon_reference
from .icon_resources import (
    AnonymousIconArchive,
    AnonymousIconResource,
    HistoricalIconEvidenceSet,
    IconObjectReference,
    TrustedIconEvidenceSource,
    iter_anonymous_blps,
)
from .map_data import GameObject, GameObjectFieldEvidence, MapData
from .object_candidates import ObjectSourceKind

_LAYER_ORDER: Final = (
    IconResolutionLayer.CURRENT_MAP,
    IconResolutionLayer.CAMPAIGN_ROOT,
    IconResolutionLayer.CLIENT,
    IconResolutionLayer.SAME_MAP_HISTORY,
    IconResolutionLayer.TRUSTED_CACHE,
)


@dataclass(frozen=True, slots=True)
class IconEvidenceBuildError(ValueError):
    """An evidence-bearing map lacks its required extraction identity."""

    map_path: str

    @override
    def __str__(self) -> str:
        return f"cannot build icon evidence for {self.map_path}: ledger is missing"


def build_icon_evidence_index(
    md: MapData,
    archives: tuple[IconArchiveLayer, ...],
    game_source: GameDataSource | None,
) -> IconEvidenceIndex:
    """Resolve exact icon references once in strict layer order."""
    references, filtered = collect_icon_field_references(md)
    history_cache: HistoricalIconEvidenceSet | None = None

    def load_history() -> HistoricalIconEvidenceSet:
        nonlocal history_cache
        if history_cache is None:
            history_cache = _history_for(md, game_source)
        return history_cache

    ordered_archives = tuple(
        sorted(
            archives,
            key=lambda item: (
                _LAYER_ORDER.index(item.layer),
                item.source_path.casefold(),
                item.source_path,
            ),
        )
    )
    resolved: list[ResolvedIconEvidence] = []
    unresolved: list[UnresolvedIconEvidence] = []
    for reference in references:
        outcome = resolve_icon_reference(
            reference,
            ordered_archives,
            game_source,
            load_history,
            md.extraction_ledger,
        )
        match outcome:
            case ResolvedIconEvidence() as row:
                resolved.append(row)
            case UnresolvedIconEvidence() as row:
                unresolved.append(row)
            case unreachable:
                assert_never(unreachable)
    anonymous, failures = collect_anonymous_icon_evidence(md, ordered_archives)
    return IconEvidenceIndex.build(
        resolved,
        unresolved,
        filtered,
        anonymous,
        failures,
    )


def collect_icon_field_references(
    md: MapData,
) -> tuple[tuple[IconObjectReference, ...], tuple[FilteredIconEvidence, ...]]:
    """Collect selected eligible fields and exact false-icon evidence."""
    references: list[IconObjectReference] = []
    filtered: list[FilteredIconEvidence] = []
    objects = tuple(obj for values in md.objects.values() for obj in values)
    for obj in objects:
        evidence = obj.icon_field_evidence
        if evidence is not None:
            references.append(_reference(md, obj, evidence))
        for field in obj.field_evidence:
            decision = classify_icon_field(
                obj.category,
                field.key,
                field.label,
                field.value_type,
                ObjectSourceKind.BINARY,
            )
            match decision.disposition:
                case IconFieldDisposition.FILTERED_NON_ICON:
                    filtered.append(FilteredIconEvidence(_reference(md, obj, field)))
                case (
                    IconFieldDisposition.ELIGIBLE
                    | IconFieldDisposition.NOT_AN_ICON_FIELD
                ):
                    pass
                case unreachable:
                    assert_never(unreachable)
    return tuple(references), tuple(filtered)


def collect_anonymous_icon_evidence(
    md: MapData,
    archives: tuple[IconArchiveLayer, ...],
) -> tuple[tuple[AnonymousIconResource, ...], int]:
    """Reopen current-map anonymous BLP evidence and count unread rows."""
    ledger = md.extraction_ledger
    if ledger is None:
        return (), 0
    expected = sum(
        entry.block_index is not None and _is_anonymous_blp(entry.internal_path)
        for entry in ledger.entries
    )
    resources: list[AnonymousIconResource] = []
    for layer in archives:
        if layer.layer is IconResolutionLayer.CURRENT_MAP and isinstance(
            layer.archive, AnonymousIconArchive
        ):
            resources.extend(iter_anonymous_blps(layer.archive, ledger))
            break
    return tuple(resources), max(0, expected - len(resources))


def _history_for(
    md: MapData,
    game_source: GameDataSource | None,
) -> HistoricalIconEvidenceSet:
    if not isinstance(game_source, TrustedIconEvidenceSource):
        return HistoricalIconEvidenceSet(available=False, resources=())
    ledger = md.extraction_ledger
    if ledger is None:
        return HistoricalIconEvidenceSet(available=False, resources=())
    return game_source.historical_icons_for(ledger.source_sha256)


def _reference(
    md: MapData,
    obj: GameObject,
    evidence: GameObjectFieldEvidence,
) -> IconObjectReference:
    plan = plan_icon_path(evidence.value)
    ledger = md.extraction_ledger
    if ledger is None:
        raise IconEvidenceBuildError(md.path)
    return IconObjectReference(
        obj.category,
        obj.obj_id,
        obj.name,
        obj.base_id,
        md.path,
        ledger.source_sha256,
        md.path,
        evidence.key,
        evidence.label,
        evidence.value_type,
        evidence.source,
        evidence.value_source,
        evidence.value,
        plan.normalized,
    )


def _is_anonymous_blp(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    return normalized.startswith("unknown/") and normalized.endswith(".blp")
