"""Load every map archive embedded in a campaign, preserving diagnostics."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from typing import Final

from .archive_inventory import InventoryArchive, build_archive_inventory
from .archive_source import BytesArchiveSource
from .campaign_budget import CampaignByteBudget, record_campaign_budget_issue
from .extraction_diagnostics import (
    DiagnosticSeverity,
    ExtractionDiagnostic,
    read_component,
    record_diagnostic,
)
from .load_context import MapLoadContext
from .map_archive_reader import DeclaredSizeArchive, MapArchiveReader
from .map_data import GameObject, MapData

type ChildMapLoader = Callable[
    [
        MapArchiveReader,
        str,
        int,
        Mapping[tuple[str, str], GameObject] | None,
        MapLoadContext,
    ],
    MapData,
]

_CHILD_ERRORS: Final = (KeyError, OSError, ValueError, IndexError, struct.error)


def load_campaign_children(
    parent: MapData,
    archive: MapArchiveReader,
    inner_maps: Sequence[str],
    depth: int,
    load_context: MapLoadContext,
    load_child: ChildMapLoader,
    *,
    max_retained_bytes: int | None = None,
    max_read_bytes: int | None = None,
) -> None:
    """Visit all children; byte budgets apply only when explicitly supplied."""
    budget = CampaignByteBudget(max_retained_bytes, max_read_bytes)
    for inner in inner_maps:
        source: BytesArchiveSource | None = None
        try:
            remaining_bytes = budget.remaining
            declared_size = (
                archive.declared_file_size(inner)
                if isinstance(archive, DeclaredSizeArchive)
                else None
            )
            reserved_bytes = budget.reserve_read(declared_size)
            if reserved_bytes is None:
                record_campaign_budget_issue(parent, inner)
                continue
            data = read_component(
                parent,
                "campaign-child",
                inner,
                lambda child_name=inner: archive.read_file(child_name),
                stage="read",
            )
            if data is None:
                continue
            budget.reconcile_read(reserved_bytes, len(data))
            if remaining_bytes is not None and len(data) > remaining_bytes:
                record_campaign_budget_issue(parent, inner)
                continue
            source = BytesArchiveSource(inner, data)
            child_context = replace(
                load_context,
                author_bundle_path=None,
                compat_bundle_path=None,
            )
            with source.open() as child_archive:
                sub = load_child(
                    child_archive,
                    inner,
                    depth + 1,
                    parent.obj_identity_index,
                    child_context,
                )
                if isinstance(child_archive, InventoryArchive):
                    sub.extraction_ledger = build_archive_inventory(
                        child_archive,
                        hashlib.sha256(data).hexdigest(),
                    )
            sub.archive_source = source
            sub.name = inner
            sub.path = inner
            parent.sub_maps.append(sub)
            budget.charge_retained(len(data))
        except _CHILD_ERRORS as exc:
            if source is not None:
                source.close()
            record_diagnostic(
                parent,
                ExtractionDiagnostic(
                    component="campaign-child",
                    source=inner,
                    stage="open/parse",
                    severity=DiagnosticSeverity.WARNING,
                    message=f"{type(exc).__name__}: {exc}".rstrip(),
                    recoverable=True,
                    exception_type=type(exc).__name__,
                ),
            )
