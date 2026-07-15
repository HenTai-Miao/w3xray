"""Resolve one icon reference through strict evidence layers."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from typing import Final, assert_never

from .extraction_ledger import ExtractionLedger
from .game_data_source import GameDataSource
from .icon_evidence_models import (
    IconArchiveLayer,
    IconLookupAttempt,
    IconResolutionLayer,
    ResolvedIconEvidence,
    UnresolvedIconEvidence,
)
from .icon_gap_diagnostics import unresolved_icon_evidence
from .icon_path_evidence import plan_icon_path
from .icon_resources import (
    HistoricalIconEvidenceSet,
    IconObjectReference,
    NamedIconResource,
    SourcedGameDataSource,
    TrustedIconEvidenceSource,
)

_READ_ERRORS: Final = (KeyError, OSError, ValueError)
_UNAVAILABLE_HISTORY: Final = HistoricalIconEvidenceSet(
    available=False,
    resources=(),
)


def resolve_icon_reference(
    reference: IconObjectReference,
    archives: tuple[IconArchiveLayer, ...],
    game_source: GameDataSource | None,
    load_history: Callable[[], HistoricalIconEvidenceSet],
    ledger: ExtractionLedger | None,
) -> ResolvedIconEvidence | UnresolvedIconEvidence:
    """Return one resolved or gap row after exact ordered attempts."""
    plan = plan_icon_path(reference.requested_path)
    attempts: list[IconLookupAttempt] = []
    history = _UNAVAILABLE_HISTORY
    history_checked = False
    if not plan.candidates:
        return unresolved_icon_evidence(
            reference,
            attempts,
            game_source,
            history,
            ledger,
            history_checked=history_checked,
            invalid=True,
        )
    for archive_layer in archives:
        for candidate in plan.candidates:
            payload = _read_archive(archive_layer, candidate)
            attempts.append(
                _attempt(
                    archive_layer.layer,
                    candidate,
                    archive_layer.source_path,
                    payload,
                )
            )
            if payload is not None:
                return _resolved(
                    reference,
                    candidate,
                    archive_layer.source_path,
                    payload,
                    archive_layer.layer,
                    attempts,
                )
    match game_source:
        case None:
            pass
        case TrustedIconEvidenceSource() as source:
            history = load_history()
            history_checked = True
            historical = _matching_history(reference, history)
            attempts.append(_history_attempt(reference, historical))
            if historical is not None:
                return _resolved(
                    reference,
                    historical.resolved_path,
                    historical.source_path,
                    historical.payload,
                    IconResolutionLayer.SAME_MAP_HISTORY,
                    attempts,
                )
            cached = _resolve_client_candidates(
                reference,
                plan.candidates,
                source,
                IconResolutionLayer.TRUSTED_CACHE,
                attempts,
            )
            if cached is not None:
                return cached
        case GameDataSource() as source:
            client = _resolve_client_candidates(
                reference,
                plan.candidates,
                source,
                IconResolutionLayer.CLIENT,
                attempts,
            )
            if client is not None:
                return client
        case unreachable:
            assert_never(unreachable)
    return unresolved_icon_evidence(
        reference,
        attempts,
        game_source,
        history,
        ledger,
        history_checked=history_checked,
    )


def _resolve_client_candidates(
    reference: IconObjectReference,
    candidates: tuple[str, ...],
    source: GameDataSource,
    layer: IconResolutionLayer,
    attempts: list[IconLookupAttempt],
) -> ResolvedIconEvidence | None:
    for candidate in candidates:
        payload, source_path = _read_client(source, candidate)
        attempts.append(_attempt(layer, candidate, source_path, payload))
        if payload is not None:
            return _resolved(
                reference,
                candidate,
                source_path,
                payload,
                layer,
                attempts,
            )
    return None


def _read_archive(layer: IconArchiveLayer, candidate: str) -> bytes | None:
    try:
        if not layer.archive.has_file(candidate):
            return None
        return layer.archive.read_file(candidate)
    except _READ_ERRORS:
        return None


def _read_client(source: GameDataSource, candidate: str) -> tuple[bytes | None, str]:
    source_path = "client-data"
    try:
        if not source.has_exact_file(candidate):
            return None, source_path
        if isinstance(source, SourcedGameDataSource):
            return source.read_file_with_source(candidate)
        return source.read_exact_file(candidate), source_path
    except _READ_ERRORS:
        return None, source_path


def _matching_history(
    reference: IconObjectReference,
    history: HistoricalIconEvidenceSet,
) -> NamedIconResource | None:
    requested_key = reference.normalized_path.casefold()
    matches = tuple(
        resource
        for resource in history.resources
        if plan_icon_path(resource.requested_path).normalized.casefold()
        == requested_key
    )
    return min(
        matches,
        key=lambda row: (
            row.resolved_path.casefold(),
            row.resolved_path,
            row.sha256,
            row.source_path.casefold(),
        ),
        default=None,
    )


def _resolved(
    reference: IconObjectReference,
    resolved_path: str,
    source_path: str,
    payload: bytes,
    layer: IconResolutionLayer,
    attempts: list[IconLookupAttempt],
) -> ResolvedIconEvidence:
    return ResolvedIconEvidence(
        reference,
        resolved_path,
        source_path,
        payload,
        hashlib.sha256(payload).hexdigest(),
        layer,
        tuple(attempts),
    )


def _attempt(
    layer: IconResolutionLayer,
    candidate: str,
    source_path: str,
    payload: bytes | None,
) -> IconLookupAttempt:
    digest = "" if payload is None else hashlib.sha256(payload).hexdigest()
    return IconLookupAttempt(
        layer,
        candidate,
        source_path,
        payload is not None,
        candidate if payload is not None else "",
        digest,
    )


def _history_attempt(
    reference: IconObjectReference,
    resource: NamedIconResource | None,
) -> IconLookupAttempt:
    if resource is None:
        return IconLookupAttempt(
            IconResolutionLayer.SAME_MAP_HISTORY,
            reference.normalized_path,
            "",
            False,
        )
    return IconLookupAttempt(
        IconResolutionLayer.SAME_MAP_HISTORY,
        reference.normalized_path,
        resource.source_path,
        True,
        resource.resolved_path,
        resource.sha256,
    )
