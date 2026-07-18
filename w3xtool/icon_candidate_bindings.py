"""Closed non-adopting candidate derivation from global icon evidence."""

from __future__ import annotations

import re
from typing import Final

from .batch_global_evidence_models import GlobalEvidenceIndex
from .icon_evidence_models import (
    IconCandidateEvidence,
    IconCandidateKind,
    IconResolutionLayer,
)
from .icon_path_evidence import plan_icon_path


_SHA256: Final = re.compile(r"[0-9a-f]{64}")
_MAP_CANDIDATE_LAYERS: Final = frozenset(
    (IconResolutionLayer.CURRENT_MAP, IconResolutionLayer.CAMPAIGN_ROOT)
)


def build_icon_candidate_bindings(
    evidence: GlobalEvidenceIndex,
) -> tuple[IconCandidateEvidence, ...]:
    """Suggest only exact cross-map path or exact anonymous-hash matches."""
    candidates: set[IconCandidateEvidence] = set()
    named = tuple(
        row
        for row in evidence.resolved
        if row.layer in _MAP_CANDIDATE_LAYERS
        and _SHA256.fullmatch(row.map_sha256) is not None
        and _SHA256.fullmatch(row.content_sha256) is not None
        and bool(row.normalized_path)
        and plan_icon_path(row.normalized_path).normalized == row.normalized_path
    )
    for gap in evidence.gaps:
        if (
            _SHA256.fullmatch(gap.map_sha256) is None
            or not gap.normalized_path
            or plan_icon_path(gap.normalized_path).normalized != gap.normalized_path
        ):
            continue
        for row in named:
            if (
                gap.map_sha256 != row.map_sha256
                and gap.normalized_path.casefold() == row.normalized_path.casefold()
            ):
                candidates.add(
                    IconCandidateEvidence(
                        IconCandidateKind.EXACT_OTHER_MAP_PATH,
                        gap.map_sha256,
                        gap.normalized_path,
                        "",
                        None,
                        row.map_sha256,
                        row.normalized_path,
                        row.content_sha256,
                    )
                )
    for anonymous in evidence.anonymous:
        if (
            _SHA256.fullmatch(anonymous.map_sha256) is None
            or _SHA256.fullmatch(anonymous.content_sha256) is None
            or anonymous.block_index < 0
        ):
            continue
        for row in named:
            if (
                anonymous.map_sha256 != row.map_sha256
                and anonymous.content_sha256 == row.content_sha256
            ):
                candidates.add(
                    IconCandidateEvidence(
                        IconCandidateKind.ANONYMOUS_HASH_MATCH,
                        "",
                        "",
                        anonymous.map_sha256,
                        anonymous.block_index,
                        row.map_sha256,
                        row.normalized_path,
                        row.content_sha256,
                    )
                )
    return GlobalEvidenceIndex.build((), (), (), candidates).candidates


__all__ = ("build_icon_candidate_bindings",)
