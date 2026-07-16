"""Shared in-memory map fixture for batch publication integration tests."""

from __future__ import annotations

import hashlib
import struct
from collections.abc import Iterable
from contextlib import nullcontext
from typing import ContextManager

from w3xtool.extraction_ledger import (
    BlockSource,
    BlockState,
    ExtractionEntry,
    build_extraction_ledger,
)
from w3xtool.icon_resources import AnonymousIconBlock
from w3xtool.item_relation_models import (
    ItemRelation,
    ItemRelationIndex,
    ItemRelationKind,
    RelationCompleteness,
    RelationConfidence,
    RelationEvidence,
    RelationObject,
)
from w3xtool.map_archive_reader import MapArchiveReader
from w3xtool.map_data import GameObject, GameObjectFieldEvidence, MapData
from w3xtool.object_text_models import (
    ObjectTextIndex,
    ObjectTextRecord,
    ObjectTextState,
)

COMPLETE_RAW = '|cffffcc00"完整\t正文\r\n第二行|r'


def _one_pixel_blp() -> bytes:
    buffer = bytearray(20 + 128 + 1024)
    buffer[0:4] = b"BLP2"
    buffer[4:9] = bytes((1, 1, 0, 0, 1))
    struct.pack_into("<II", buffer, 12, 1, 1)
    struct.pack_into("<I", buffer, 20, len(buffer))
    struct.pack_into("<I", buffer, 84, 1)
    buffer[148:152] = bytes((10, 20, 30, 255))
    buffer.append(0)
    return bytes(buffer)


class _Block:
    def __init__(self, file_size: int) -> None:
        self.file_size = file_size


class _Archive:
    path = "fixture.w3x"

    def __init__(self, named: dict[str, bytes], anonymous: dict[int, bytes]) -> None:
        self._data = b""
        self._named = {name.casefold(): payload for name, payload in named.items()}
        self._anonymous = anonymous
        self._blocks = {
            index: _Block(len(payload)) for index, payload in anonymous.items()
        }

    def has_file(self, name: str) -> bool:
        return name.casefold() in self._named

    def read_file(self, name: str) -> bytes:
        return self._named[name.casefold()]

    def list_files(self) -> list[str]:
        return list(self._named)

    def close(self) -> None:
        """The in-memory fake owns no external resource."""

    def iter_blocks(self) -> Iterable[tuple[int, AnonymousIconBlock]]:
        return tuple(self._blocks.items())

    def read_block_anon(self, block: AnonymousIconBlock) -> bytes | None:
        return next(
            (
                self._anonymous[index]
                for index, candidate in self._blocks.items()
                if candidate is block
            ),
            None,
        )


class ArchiveSource:
    def __init__(self, archive: _Archive) -> None:
        self.path = archive.path
        self.archive = archive
        self.closed = False

    def open(self) -> ContextManager[MapArchiveReader]:
        return nullcontext(self.archive)

    def close(self) -> None:
        self.closed = True


def loaded_map(
    source_path: str,
    icon_path: str,
    *,
    text_state: ObjectTextState = ObjectTextState.MAP_VALUE,
    relation_completeness: RelationCompleteness = RelationCompleteness.COMPLETE,
) -> tuple[MapData, ArchiveSource]:
    payload = _one_pixel_blp()
    archive = _Archive({r"Icons\BTNHero.blp": payload}, {7: payload})
    source = ArchiveSource(archive)
    icon_evidence = GameObjectFieldEvidence(
        key="aart",
        label="图标 - 普通",
        value=icon_path,
        source="war3map.w3a",
        source_priority=40,
        value_type="icon",
    )
    ability_object = GameObject(
        category="技能",
        ext="w3a",
        obj_id="A001",
        base_id="AHbz",
        name="暴风雪",
        is_custom=True,
        icon=icon_path,
        field_values={"aub1": "|cffffcc00说明|r|n第二行"},
        field_sources={"aub1": "war3map.w3a"},
        field_evidence=(icon_evidence,),
        icon_field_evidence=icon_evidence,
    )
    digest = hashlib.sha256(payload).hexdigest()
    entry = ExtractionEntry(
        block_index=7,
        internal_path="Unknown/block_000007.blp",
        state=BlockState.DECODED,
        source=BlockSource.ARCHIVE_RECOVERED,
        declared_size=len(payload),
        written_size=len(payload),
        sha256=digest,
        encrypted=False,
        error_code="",
        detail="",
    )
    object_texts = ObjectTextIndex.build(
        (
            ObjectTextRecord(
                category="技能",
                object_id="A001",
                base_id="AHbz",
                object_name="暴风雪",
                is_custom=True,
                role="扩展提示",
                field_key="aub1",
                field_label="提示工具 - 扩展",
                level=1,
                raw_value=COMPLETE_RAW,
                readable_value='"完整\t正文\n第二行',
                source_kind="地图二进制",
                source_path="war3map.w3a",
                state=text_state,
                placeholder=False,
                conflict_group="",
                evidence_ordinal=1,
            ),
        )
    )
    target_item = RelationObject("物品", "I001", "测试装备")
    relations = ItemRelationIndex.build(
        (
            ItemRelation(
                kind=ItemRelationKind.UNIT_DROP,
                item=target_item,
                source=RelationObject("单位", "n001", "测试怪物"),
                evidence=RelationEvidence(source="war3mapUnits.doo", offset=42),
                confidence=RelationConfidence.CONFIRMED,
                completeness=relation_completeness,
                group_index=0,
                entry_index=0,
                chance=100,
            ),
            ItemRelation(
                kind=ItemRelationKind.ITEM_ABILITY,
                item=target_item,
                skill=RelationObject("技能", "A001", "暴风雪"),
                evidence=RelationEvidence(source="war3map.w3t", field_key="abilList"),
                confidence=RelationConfidence.CONFIRMED,
                completeness=relation_completeness,
            ),
        )
    )
    return (
        MapData(
            path=source_path,
            name="集成测试图",
            objects={"技能": [ability_object]},
            archive_source=source,
            extraction_ledger=build_extraction_ledger(source_path, "a" * 64, (entry,)),
            object_texts=object_texts,
            item_relations=relations,
        ),
        source,
    )
