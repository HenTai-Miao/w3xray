"""Collect batch-wide icon evidence from verified map publications only."""

from __future__ import annotations

from pathlib import Path

from .batch_global_evidence_models import (
    GlobalEvidenceIndex,
    GlobalEvidenceError,
    GlobalIconGap,
)
from .batch_global_evidence_reader import read_global_gap_rows, read_global_icon_rows
from .batch_manifest_validation import verify_map_publication
from .batch_models import BatchState
from .batch_status import PublicationResult
from .icon_candidate_bindings import build_icon_candidate_bindings
from .safe_output import safe_destination


_COLLECTED_REPORTS = frozenset(("图标索引.tsv", "图标未解析.tsv"))


def collect_global_evidence(
    output_root: str | Path,
    state: BatchState,
) -> GlobalEvidenceIndex:
    """Read only state-selected, manifest-verified map publication reports."""
    root = Path(output_root)
    gaps = []
    resolved = []
    anonymous = []
    for result in state.results:
        if result.publication_result is not PublicationResult.PUBLISHED:
            continue
        destination = safe_destination(str(root), result.output_directory)
        if destination is None:
            raise GlobalEvidenceError("unsafe map output directory")
        validation = verify_map_publication(
            Path(destination),
            result,
            requested_reports=_COLLECTED_REPORTS,
        )
        if not validation.valid:
            raise GlobalEvidenceError(f"invalid map publication: {validation.code}")
        map_gaps = read_global_gap_rows(
            validation.reports.content("图标未解析.tsv"), result
        )
        named_rows, anonymous_rows = read_global_icon_rows(
            validation.reports.content("图标索引.tsv"), result
        )
        _require_map_counts(result, map_gaps, named_rows, anonymous_rows)
        _require_unique_icons(named_rows, anonymous_rows)
        gaps.extend(map_gaps)
        resolved.extend(named_rows)
        anonymous.extend(anonymous_rows)
    _require_unique_gap_paths(gaps)
    base = GlobalEvidenceIndex.build(gaps, resolved, anonymous, ())
    candidates = build_icon_candidate_bindings(base)
    return GlobalEvidenceIndex.build(gaps, resolved, anonymous, candidates)


def _require_map_counts(result, gaps, named, anonymous) -> None:
    if (
        len(gaps) != result.unresolved_icon_count
        or sum(row.reference_count for row in gaps)
        != result.unresolved_icon_reference_count
        or len(named) != result.named_icon_count
        or len(anonymous) != result.anonymous_icon_count
    ):
        raise GlobalEvidenceError("map icon counts disagree with supplied state")


def _require_unique_icons(named, anonymous) -> None:
    if len(set(named)) != len(named):
        raise GlobalEvidenceError("duplicate named global icon identity")
    if len(set(anonymous)) != len(anonymous):
        raise GlobalEvidenceError("duplicate anonymous global icon identity")


def _require_unique_gap_paths(gaps: list[GlobalIconGap]) -> None:
    identities = {
        (row.map_path.casefold(), row.map_sha256, row.normalized_path.casefold())
        for row in gaps
    }
    if len(identities) != len(gaps):
        raise GlobalEvidenceError("duplicate global map/path gap row")


__all__ = ("GlobalEvidenceError", "collect_global_evidence")
