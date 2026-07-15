"""Closed immutable variants for auditable icon resolution evidence."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import TYPE_CHECKING, Literal, assert_never, override

from .icon_field_evidence import IconFieldDisposition

if TYPE_CHECKING:
    from .icon_resources import (
        IconObjectReference,
        NamedIconArchive,
    )


class IconGapReason(StrEnum):
    """Primary reason an eligible icon reference remains unresolved."""

    INVALID_REFERENCE = "invalid_reference"
    NAMED_RESOURCE_MISSING = "named_resource_missing"
    ANONYMOUS_PAYLOAD_UNBOUND = "anonymous_payload_unbound"
    CLIENT_SOURCE_UNAVAILABLE = "client_source_unavailable"
    HISTORICAL_CLIENT_MISS = "historical_client_miss"
    ARCHIVE_NAME_UNAVAILABLE = "archive_name_unavailable"
    ARCHIVE_BLOCK_DAMAGED = "archive_block_damaged"


class IconDiagnosticFlag(StrEnum):
    """Independent static facts retained beside the primary gap reason."""

    CLIENT_NOT_PROVIDED = "client_not_provided"
    HISTORICAL_EVIDENCE_CHECKED = "historical_evidence_checked"
    ANONYMOUS_BLP_PRESENT = "anonymous_blp_present"
    ARCHIVE_HAS_RAW_BLOCK = "archive_has_raw_block"
    ARCHIVE_HAS_DAMAGED_BLOCK = "archive_has_damaged_block"
    ARCHIVE_HAS_RESTRICTED_BLOCK = "archive_has_restricted_block"


class IconResolutionLayer(StrEnum):
    """Strict lookup layers in documented precedence order."""

    CURRENT_MAP = "current_map"
    CAMPAIGN_ROOT = "campaign_root"
    CLIENT = "client"
    SAME_MAP_HISTORY = "same_map_history"
    TRUSTED_CACHE = "trusted_cache"


@dataclass(frozen=True, slots=True)
class IconArchiveLayerError(ValueError):
    """A non-archive resolution layer was bound to an archive reader."""

    layer: IconResolutionLayer
    source_path: str

    @override
    def __str__(self) -> str:
        return f"icon archive layer {self.layer.value} is invalid: {self.source_path}"


@dataclass(frozen=True, slots=True)
class IconArchiveLayer:
    """One exact named archive and its logical provenance."""

    layer: IconResolutionLayer
    archive: NamedIconArchive
    source_path: str

    def __post_init__(self) -> None:
        match self.layer:
            case IconResolutionLayer.CURRENT_MAP | IconResolutionLayer.CAMPAIGN_ROOT:
                pass
            case (
                IconResolutionLayer.CLIENT
                | IconResolutionLayer.SAME_MAP_HISTORY
                | IconResolutionLayer.TRUSTED_CACHE
            ):
                raise IconArchiveLayerError(self.layer, self.source_path)
            case unreachable:
                assert_never(unreachable)


@dataclass(frozen=True, slots=True)
class IconLookupAttempt:
    """One exact candidate lookup with structured outcome evidence."""

    layer: IconResolutionLayer
    candidate_path: str
    source_path: str
    found: bool
    resolved_path: str = ""
    content_sha256: str = ""


@dataclass(frozen=True, slots=True)
class ResolvedIconEvidence:
    """An eligible reference bound to hash-verified bytes."""

    reference: IconObjectReference
    resolved_path: str
    source_path: str
    payload: bytes
    content_sha256: str
    layer: IconResolutionLayer
    attempts: tuple[IconLookupAttempt, ...]


@dataclass(frozen=True, slots=True)
class UnresolvedIconEvidence:
    """An eligible reference with a stable primary gap reason."""

    reference: IconObjectReference
    reason: IconGapReason
    diagnostics: tuple[IconDiagnosticFlag, ...]
    attempts: tuple[IconLookupAttempt, ...]

    def __post_init__(self) -> None:
        ordered = tuple(sorted(set(self.diagnostics), key=lambda flag: flag.value))
        if ordered != self.diagnostics:
            object.__setattr__(self, "diagnostics", ordered)


@dataclass(frozen=True, slots=True)
class FilteredIconEvidence:
    """An exact false-icon field excluded before path lookup."""

    reference: IconObjectReference
    reason: IconFieldDisposition = IconFieldDisposition.FILTERED_NON_ICON


class IconCandidateKind(StrEnum):
    """Non-authoritative batch-wide candidate evidence kinds."""

    EXACT_OTHER_MAP_PATH = "exact_other_map_path"
    ANONYMOUS_HASH_MATCH = "anonymous_hash_match"


@dataclass(frozen=True, slots=True)
class IconCandidateEvidence:
    """A non-adopted hint retained without changing resolution state."""

    kind: IconCandidateKind
    requested_map_sha256: str
    requested_path: str
    anonymous_map_sha256: str
    anonymous_block_index: int | None
    candidate_map_sha256: str
    candidate_path: str
    content_sha256: str
    adopted: Literal[False] = field(default=False, init=False)
