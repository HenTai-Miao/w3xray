"""Named and anonymous icon resource discovery tests."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from w3xtool.extraction_ledger import (
    BlockSource,
    BlockState,
    ExtractionEntry,
    build_extraction_ledger,
)
from w3xtool.icon_resources import (
    collect_icon_references,
    iter_anonymous_blps,
    resolve_named_icon,
)
from w3xtool.map_data import GameObject


def _game_object(
    *,
    category: str,
    obj_id: str,
    icon: str,
) -> GameObject:
    return GameObject(
        category=category,
        ext="w3u",
        obj_id=obj_id,
        base_id=obj_id,
        name=f"对象 {obj_id}",
        is_custom=True,
        icon=icon,
    )


class _FakeNamedSource:
    def __init__(self, path: str, files: dict[str, bytes]) -> None:
        self.path = path
        self._files = {name.replace("/", "\\").casefold(): payload for name, payload in files.items()}

    def has_file(self, name: str) -> bool:
        return name.replace("/", "\\").casefold() in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[name.replace("/", "\\").casefold()]


class _FakeClientSource:
    def __init__(self, source_path: str, files: dict[str, bytes]) -> None:
        self.source_path = source_path
        self._files = {name.casefold(): payload for name, payload in files.items()}

    def has_file(self, name: str) -> bool:
        return name.casefold() in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[name.casefold()]

    def read_file_with_source(self, name: str) -> tuple[bytes, str]:
        return self.read_file(name), self.source_path

    def close(self) -> None:
        """The fake owns no external resource."""


@dataclass(frozen=True, slots=True)
class _Block:
    file_size: int


class _FakeAnonymousArchive:
    def __init__(self, blocks: dict[int, bytes]) -> None:
        self._blocks = blocks
        self.read_indexes: list[int] = []

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple((index, _Block(len(payload))) for index, payload in self._blocks.items())

    def read_block_anon(self, block: _Block) -> bytes | None:
        for index, payload in self._blocks.items():
            if len(payload) == block.file_size and index not in self.read_indexes:
                self.read_indexes.append(index)
                return payload
        return None


def _entry(block_index: int, path: str, payload: bytes) -> ExtractionEntry:
    return ExtractionEntry(
        block_index=block_index,
        internal_path=path,
        state=BlockState.DECODED,
        source=BlockSource.ARCHIVE_RECOVERED,
        declared_size=len(payload),
        written_size=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        encrypted=False,
        error_code="",
        detail="",
    )


def test_named_icon_collection_deduplicates_paths_and_keeps_all_references() -> None:
    # Given
    objects = (
        _game_object(
            category="单位",
            obj_id="H001",
            icon="ReplaceableTextures/CommandButtons/BTNHero.blp",
        ),
        _game_object(
            category="技能",
            obj_id="A001",
            icon="replaceabletextures\\commandbuttons\\BTNHero.blp",
        ),
    )

    # When
    references = collect_icon_references(objects)

    # Then
    assert len(references) == 1
    assert {(ref.category, ref.object_id) for ref in references[0].objects} == {
        ("单位", "H001"),
        ("技能", "A001"),
    }


def test_named_icon_resolution_prefers_map_and_records_the_true_source() -> None:
    # Given
    (reference,) = collect_icon_references(
        (_game_object(category="单位", obj_id="H001", icon="Icons/BTNHero"),),
    )
    map_source = _FakeNamedSource("map.w3x", {"Icons\\BTNHero.blp": b"BLP1map"})
    client_source = _FakeClientSource("War3Patch.mpq", {"Icons\\BTNHero.blp": b"BLP1client"})

    # When
    resource = resolve_named_icon(reference, (map_source,), client_source)

    # Then
    assert resource is not None
    assert (resource.payload, resource.resolved_path, resource.source_path) == (
        b"BLP1map",
        "Icons\\BTNHero.blp",
        "map.w3x",
    )


def test_named_icon_resolution_uses_client_archive_provenance() -> None:
    # Given
    (reference,) = collect_icon_references(
        (_game_object(category="技能", obj_id="A001", icon="Icons\\BTNSpell.blp"),),
    )
    client_source = _FakeClientSource("War3x.mpq", {"Icons\\BTNSpell.blp": b"BLP1client"})

    # When
    resource = resolve_named_icon(reference, (), client_source)

    # Then
    assert resource is not None
    assert resource.source_path == "War3x.mpq"
    assert resource.sha256 == hashlib.sha256(b"BLP1client").hexdigest()


def test_anonymous_blp_name_uses_block_and_payload_digest() -> None:
    # Given
    payload = b"BLP1payload"
    archive = _FakeAnonymousArchive({17: payload})
    ledger = build_extraction_ledger(
        "map.w3x",
        "a" * 64,
        (_entry(17, "Unknown/block_000017.blp", payload),),
    )

    # When
    resources = tuple(iter_anonymous_blps(archive, ledger))

    # Then
    digest = hashlib.sha256(payload).hexdigest()
    assert resources[0].basename == f"block_000017_{digest[:8]}"
    assert resources[0].original_path is None
    assert resources[0].source_path == "map.w3x"
    assert archive.read_indexes == [17]


def test_anonymous_discovery_ignores_named_blps_and_hash_mismatches() -> None:
    # Given
    anonymous_payload = b"BLP1changed"
    archive = _FakeAnonymousArchive({2: b"BLP1named", 3: anonymous_payload})
    ledger = build_extraction_ledger(
        "map.w3x",
        "a" * 64,
        (
            _entry(2, "Icons/Named.blp", b"BLP1named"),
            _entry(3, "Unknown/block_000003.blp", b"BLP1original"),
        ),
    )

    # When
    resources = tuple(iter_anonymous_blps(archive, ledger))

    # Then
    assert resources == ()
