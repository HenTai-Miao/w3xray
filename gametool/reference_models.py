"""Immutable, source-qualified records for the offline reference browser."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReferenceSource:
    id: str
    path: str
    sha256: str
    provenance: str
    build: str = "unrecorded"
    state: str = "static-definition"
    fingerprint_basis: str = "file-bytes"
    source_file_sha256: str = ""
    source_file_state: str = ""
    member_path: str = ""
    container_sha256: str = ""
    source_file_identity: tuple[int, int] | None = None
    source_descriptor_stamp: tuple[int, ...] = ()
    source_path_stamp: tuple[int, ...] = ()


@dataclass(frozen=True, slots=True)
class ReferenceMapScope:
    """One archive context, including empty or failed campaign chapters."""

    scope: str
    archive_path: str
    member_path: str
    name: str
    sha256: str
    category_counts: tuple[tuple[str, int], ...] = ()
    shared_scope: str = ""
    shared_references: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[str, ...] = ()
    complete: bool = True


@dataclass(frozen=True, slots=True)
class ReferenceValue:
    key: str
    label: str
    value: str
    value_type: str = ""
    source: str = ""
    provenance: str = ""
    state: str = "static-definition"
    aliases: tuple[str, ...] = ()
    extras: tuple[tuple[str, str], ...] = ()
    category: str = ""
    object_id: str = ""

    def search_fields(self) -> Iterator[str]:
        yield from (
            self.key,
            self.label,
            self.value,
            self.value_type,
            self.source,
            self.provenance,
            self.state,
            self.category,
            self.object_id,
            *self.aliases,
        )
        for label, value in self.extras:
            yield label
            yield value


@dataclass(frozen=True, slots=True)
class ReferenceRecord:
    kind: str
    id: str
    label: str
    category: str = ""
    scope: str = "builtin"
    aliases: tuple[str, ...] = ()
    categories: tuple[str, ...] = ()
    builds: tuple[str, ...] = ("unrecorded",)
    sources: tuple[str, ...] = ()
    state: str = "static-definition"
    values: tuple[ReferenceValue, ...] = ()
    details: tuple[tuple[str, str], ...] = ()
    diagnostics: tuple[str, ...] = ()
    raw_rows: tuple[tuple[str, ...], ...] = ()
    coverage: dict[str, Any] | None = None

    def search_fields(self) -> Iterator[str]:
        yield from (
            self.id,
            self.label,
            self.category,
            self.scope,
            self.state,
            *self.aliases,
            *self.categories,
            *self.builds,
            *self.sources,
            *self.diagnostics,
        )
        for label, value in self.details:
            yield label
            yield value
        for field in self.values:
            yield from field.search_fields()


@dataclass(frozen=True, slots=True)
class ReferenceCatalog:
    records: tuple[ReferenceRecord, ...]
    sources: tuple[ReferenceSource, ...]
    diagnostics: tuple[str, ...] = ()
    input_roots: tuple[str, ...] = ()
    map_path: str = ""
    map_scopes: tuple[ReferenceMapScope, ...] = ()
    source_counts: tuple[tuple[str, int], ...] = ()
    input_files: tuple[str, ...] = ()

    @property
    def complete(self) -> bool:
        return not self.diagnostics


@dataclass(frozen=True, slots=True)
class ReferenceSearchResult:
    records: tuple[ReferenceRecord, ...]
    sources: tuple[ReferenceSource, ...]
    diagnostics: tuple[str, ...]
    total: int
    matched: int
    omitted: int
    query: str = ""
    kind: str = "all"
    category: str = ""
    build: str = ""
    source: str = ""
    limit: int = 0
    catalog_complete: bool = True
    recovery: tuple[str, ...] = ()
    input_roots: tuple[str, ...] = ()
    map_path: str = ""
    map_scopes: tuple[ReferenceMapScope, ...] = ()
    source_counts: tuple[tuple[str, int], ...] = ()
    input_files: tuple[str, ...] = ()
