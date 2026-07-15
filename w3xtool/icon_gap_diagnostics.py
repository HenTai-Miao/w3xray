"""Derive stable icon gap diagnostics and one primary reason."""

from __future__ import annotations

from typing import Final

from .extraction_ledger import BlockState, ExtractionLedger
from .game_data_source import GameDataSource
from .icon_evidence_models import (
    IconDiagnosticFlag,
    IconGapReason,
    IconLookupAttempt,
    UnresolvedIconEvidence,
)
from .icon_resources import (
    HistoricalIconEvidenceSet,
    IconObjectReference,
    TrustedIconEvidenceSource,
)

_GAP_REASON_PRIORITY: Final = (
    IconGapReason.INVALID_REFERENCE,
    IconGapReason.ARCHIVE_BLOCK_DAMAGED,
    IconGapReason.ARCHIVE_NAME_UNAVAILABLE,
    IconGapReason.ANONYMOUS_PAYLOAD_UNBOUND,
    IconGapReason.HISTORICAL_CLIENT_MISS,
    IconGapReason.CLIENT_SOURCE_UNAVAILABLE,
    IconGapReason.NAMED_RESOURCE_MISSING,
)


def unresolved_icon_evidence(
    reference: IconObjectReference,
    attempts: list[IconLookupAttempt],
    game_source: GameDataSource | None,
    history: HistoricalIconEvidenceSet,
    ledger: ExtractionLedger | None,
    *,
    invalid: bool = False,
) -> UnresolvedIconEvidence:
    """Select the fixed-priority reason while retaining every diagnostic."""
    diagnostics = _diagnostics(ledger, game_source)
    reasons = {IconGapReason.NAMED_RESOURCE_MISSING}
    if invalid:
        reasons.add(IconGapReason.INVALID_REFERENCE)
    if IconDiagnosticFlag.ARCHIVE_HAS_DAMAGED_BLOCK in diagnostics:
        reasons.add(IconGapReason.ARCHIVE_BLOCK_DAMAGED)
    if diagnostics.intersection(
        (
            IconDiagnosticFlag.ARCHIVE_HAS_RAW_BLOCK,
            IconDiagnosticFlag.ARCHIVE_HAS_RESTRICTED_BLOCK,
        )
    ):
        reasons.add(IconGapReason.ARCHIVE_NAME_UNAVAILABLE)
    if IconDiagnosticFlag.ANONYMOUS_BLP_PRESENT in diagnostics:
        reasons.add(IconGapReason.ANONYMOUS_PAYLOAD_UNBOUND)
    if history.available:
        reasons.add(IconGapReason.HISTORICAL_CLIENT_MISS)
    if game_source is None or isinstance(game_source, TrustedIconEvidenceSource):
        if not history.available:
            reasons.add(IconGapReason.CLIENT_SOURCE_UNAVAILABLE)
    reason = next(item for item in _GAP_REASON_PRIORITY if item in reasons)
    return UnresolvedIconEvidence(
        reference, reason, tuple(diagnostics), tuple(attempts)
    )


def _diagnostics(
    ledger: ExtractionLedger | None,
    game_source: GameDataSource | None,
) -> set[IconDiagnosticFlag]:
    flags: set[IconDiagnosticFlag] = set()
    if game_source is None or isinstance(game_source, TrustedIconEvidenceSource):
        flags.add(IconDiagnosticFlag.CLIENT_NOT_PROVIDED)
    if isinstance(game_source, TrustedIconEvidenceSource):
        flags.add(IconDiagnosticFlag.HISTORICAL_EVIDENCE_CHECKED)
    if ledger is None:
        return flags
    states = {entry.state for entry in ledger.entries}
    if BlockState.RAW_ONLY in states:
        flags.add(IconDiagnosticFlag.ARCHIVE_HAS_RAW_BLOCK)
    if BlockState.DAMAGED in states:
        flags.add(IconDiagnosticFlag.ARCHIVE_HAS_DAMAGED_BLOCK)
    if BlockState.ENCRYPTED_BLOCKED in states:
        flags.add(IconDiagnosticFlag.ARCHIVE_HAS_RESTRICTED_BLOCK)
    if any(_is_anonymous_blp(entry.internal_path) for entry in ledger.entries):
        flags.add(IconDiagnosticFlag.ANONYMOUS_BLP_PRESENT)
    return flags


def _is_anonymous_blp(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    return normalized.startswith("unknown/") and normalized.endswith(".blp")
