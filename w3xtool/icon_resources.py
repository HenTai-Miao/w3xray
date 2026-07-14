"""Discover provable named and anonymous icon payloads without image caching."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from .extraction_ledger import BlockSource, BlockState, ExtractionLedger
from .game_data_source import GameDataSource
from .map_data import GameObject


class NamedIconArchive(Protocol):
    """Named-member archive surface used by icon lookup."""

    @property
    def path(self) -> str: ...

    def has_file(self, name: str) -> bool: ...

    def read_file(self, name: str) -> bytes: ...


class AnonymousIconBlock(Protocol):
    """Opaque archive block metadata accepted by anonymous reads."""

    @property
    def file_size(self) -> int: ...


@runtime_checkable
class AnonymousIconArchive(Protocol):
    """Block-level surface used to reopen ledger evidence."""

    def iter_blocks(self) -> Iterable[tuple[int, AnonymousIconBlock]]: ...

    def read_block_anon(self, block: AnonymousIconBlock) -> bytes | None: ...


@runtime_checkable
class SourcedGameDataSource(Protocol):
    """Optional client-data capability that reports exact provenance."""

    def read_file_with_source(self, name: str) -> tuple[bytes, str]: ...


@dataclass(frozen=True, slots=True)
class IconObjectReference:
    category: str
    object_id: str
    object_name: str


@dataclass(frozen=True, slots=True)
class IconReference:
    requested_path: str
    normalized_path: str
    objects: tuple[IconObjectReference, ...]


@dataclass(frozen=True, slots=True)
class NamedIconResource:
    requested_path: str
    normalized_path: str
    resolved_path: str
    source_path: str
    payload: bytes
    sha256: str
    objects: tuple[IconObjectReference, ...]


@dataclass(frozen=True, slots=True)
class AnonymousIconResource:
    block_index: int
    payload: bytes
    sha256: str
    basename: str
    source_path: str
    ledger_source: BlockSource
    ledger_state: BlockState
    original_path: None = None


def collect_icon_references(objects: Iterable[GameObject]) -> tuple[IconReference, ...]:
    """Deduplicate icon paths while preserving every referring object."""
    grouped: dict[str, tuple[str, set[IconObjectReference]]] = {}
    for item in objects:
        normalized = _normalize_icon_path(item.icon)
        if not normalized:
            continue
        key = normalized.casefold()
        existing = grouped.get(key)
        if existing is None:
            existing = (normalized, set())
            grouped[key] = existing
        existing[1].add(IconObjectReference(item.category, item.obj_id, item.name))
    return tuple(
        IconReference(
            requested_path=normalized,
            normalized_path=normalized,
            objects=tuple(sorted(refs, key=_object_reference_key)),
        )
        for _key, (normalized, refs) in sorted(grouped.items())
    )


def resolve_named_icon(
    reference: IconReference,
    map_archives: Iterable[NamedIconArchive],
    game_source: GameDataSource | None,
) -> NamedIconResource | None:
    """Resolve raw icon bytes in map/campaign/client priority order."""
    candidates = _path_candidates(reference.normalized_path)
    for archive in map_archives:
        for candidate in candidates:
            payload = _read_named(archive, candidate)
            if payload is not None:
                return _named_resource(reference, candidate, archive.path, payload)
    if game_source is None:
        return None
    for candidate in candidates:
        resolved = _read_client(game_source, candidate)
        if resolved is not None:
            payload, source_path = resolved
            return _named_resource(reference, candidate, source_path, payload)
    return None


def iter_anonymous_blps(
    archive: AnonymousIconArchive,
    ledger: ExtractionLedger,
) -> Iterator[AnonymousIconResource]:
    """Yield hash-verified anonymous BLP blocks once in ledger order."""
    blocks = {index: block for index, block in archive.iter_blocks()}
    seen: set[int] = set()
    for entry in ledger.entries:
        block_index = entry.block_index
        if (
            block_index is None
            or block_index in seen
            or not _is_anonymous_blp(entry.internal_path)
        ):
            continue
        seen.add(block_index)
        block = blocks.get(block_index)
        if block is None:
            continue
        try:
            payload = archive.read_block_anon(block)
        except KeyError, OSError, ValueError:
            continue
        if payload is None or not payload.startswith((b"BLP1", b"BLP2")):
            continue
        digest = hashlib.sha256(payload).hexdigest()
        if digest != entry.sha256:
            continue
        yield AnonymousIconResource(
            block_index=block_index,
            payload=payload,
            sha256=digest,
            basename=f"block_{block_index:06d}_{digest[:8]}",
            source_path=ledger.source_path,
            ledger_source=entry.source,
            ledger_state=entry.state,
        )


def _normalize_icon_path(path: str) -> str:
    return path.strip().strip('"').replace("/", "\\")


def _path_candidates(path: str) -> tuple[str, ...]:
    leaf = path.rsplit("\\", 1)[-1]
    base = path.rsplit(".", 1)[0] if "." in leaf else path
    ordered = (path, f"{base}.blp", f"{base}.tga", f"{base}.dds")
    seen: set[str] = set()
    return tuple(
        item
        for item in ordered
        if not (item.casefold() in seen or seen.add(item.casefold()))
    )


def _read_named(source: NamedIconArchive, name: str) -> bytes | None:
    try:
        return source.read_file(name) if source.has_file(name) else None
    except KeyError, OSError, ValueError:
        return None


def _read_client(source: GameDataSource, name: str) -> tuple[bytes, str] | None:
    try:
        if not source.has_file(name):
            return None
        if isinstance(source, SourcedGameDataSource):
            return source.read_file_with_source(name)
        return source.read_file(name), "client-data"
    except KeyError, OSError, ValueError:
        return None


def _named_resource(
    reference: IconReference,
    resolved_path: str,
    source_path: str,
    payload: bytes,
) -> NamedIconResource:
    return NamedIconResource(
        requested_path=reference.requested_path,
        normalized_path=reference.normalized_path,
        resolved_path=resolved_path,
        source_path=source_path,
        payload=payload,
        sha256=hashlib.sha256(payload).hexdigest(),
        objects=reference.objects,
    )


def _is_anonymous_blp(path: str) -> bool:
    normalized = path.replace("\\", "/").casefold()
    return normalized.startswith("unknown/") and normalized.endswith(".blp")


def _object_reference_key(item: IconObjectReference) -> tuple[str, str, str]:
    return item.category.casefold(), item.object_id, item.object_name
