"""Contracts for trusted and anonymous Warcraft text-object sources."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import FrozenInstanceError, dataclass
from types import MappingProxyType

import pytest

from w3xtool.object_text_sources import (
    TextObjectRecord,
    TextObjectSourceKind,
    collect_text_object_records,
    merge_text_object_records,
)


class FakeArchive:
    def __init__(
        self,
        files: dict[str, bytes],
        *,
        reverse_listing: bool = False,
        expose_listing: bool = True,
    ) -> None:
        self._files = {
            self._normalize(name): (name, payload) for name, payload in files.items()
        }
        self._reverse_listing = reverse_listing
        self._expose_listing = expose_listing

    @property
    def path(self) -> str:
        return "fixture.w3x"

    @property
    def _data(self) -> bytes:
        return b""

    def has_file(self, name: str) -> bool:
        return self._normalize(name) in self._files

    def read_file(self, name: str) -> bytes:
        return self._files[self._normalize(name)][1]

    def list_files(self) -> list[str]:
        if not self._expose_listing:
            return []
        names = [name for name, _payload in self._files.values()]
        return list(reversed(names)) if self._reverse_listing else names

    def close(self) -> None:
        return

    @staticmethod
    def _normalize(name: str) -> str:
        return name.replace("/", "\\").casefold()


@dataclass(frozen=True, slots=True)
class FakeBlock:
    payload: bytes

    @property
    def file_size(self) -> int:
        return len(self.payload)


class FakeAnonymousArchive(FakeArchive):
    def __init__(self, blocks: tuple[FakeBlock, ...]) -> None:
        super().__init__({})
        self._blocks = blocks

    def iter_blocks(self) -> tuple[tuple[int, FakeBlock], ...]:
        return tuple(enumerate(self._blocks))

    def peek_block(self, block: FakeBlock, n: int = 64) -> bytes:
        return block.payload[:n]

    def read_block_anon(self, block: FakeBlock) -> bytes:
        return block.payload


def test_named_gbk_strings_file_is_decoded_below_anonymous_threshold() -> None:
    # Given: a trusted reference file that is absent from the archive listing.
    archive = FakeArchive(
        {
            "Units\\HumanUnitStrings.txt": (
                "[H001]\nName=圣骑士\nPropernames=光明使者\n".encode("gbk")
            ),
        },
        expose_listing=False,
    )

    # When: trusted text sources are collected.
    records = collect_text_object_records(archive)

    # Then: its single GBK object is retained without anonymous thresholding.
    assert [(record.obj_id, record.fields["Name"]) for record in records] == [
        ("H001", "圣骑士")
    ]


def test_known_trusted_name_is_checked_without_archive_listing() -> None:
    # Given: an externally supplied trusted name hidden from the listing.
    archive = FakeArchive(
        {"Custom\\BonusUnitFunc.txt": b"[H001]\nHP=1000\n"},
        expose_listing=False,
    )

    # When: the caller supplies that candidate name.
    records = collect_text_object_records(
        archive, known_names=("Custom\\BonusUnitFunc.txt",)
    )

    # Then: direct has_file lookup finds the source.
    assert [(record.obj_id, record.fields["HP"]) for record in records] == [
        ("H001", "1000")
    ]


def test_func_and_strings_merge_by_field_role_not_archive_order() -> None:
    # Given: Func and Strings sources listed in reverse order.
    archive = FakeArchive(
        {
            "Units\\HumanUnitStrings.txt": b"[H001]\nName=Localized\nUbertip=Readable\n",
            "Units\\HumanUnitFunc.txt": b"[H001]\nName=Internal\nHP=1000\n",
        },
        reverse_listing=True,
    )

    # When: the collected records are merged.
    record = merge_text_object_records(collect_text_object_records(archive))[0]

    # Then: Strings wins display fields and Func wins non-display fields.
    assert dict(record.fields) == {
        "Name": "Localized",
        "Ubertip": "Readable",
        "HP": "1000",
    }


def test_empty_func_value_does_not_replace_nonempty_value() -> None:
    # Given: a high-priority Func field with an empty value.
    archive = FakeArchive(
        {
            "Units\\HumanUnitStrings.txt": b"[H001]\nHP=900\n",
            "Units\\HumanUnitFunc.txt": b"[H001]\nHP=\n",
        },
    )

    # When: records are merged.
    record = merge_text_object_records(collect_text_object_records(archive))[0]

    # Then: the nonempty lower-priority value remains.
    assert dict(record.fields) == {"HP": "900"}


def test_merge_is_byte_stable_when_archive_listing_order_reverses() -> None:
    # Given: equivalent archives with opposing list order and same-priority values.
    files = {
        "Units\\AlphaUnitFunc.txt": b"[H001]\nHP=900\n",
        "Units\\ZuluUnitFunc.txt": b"[H001]\nHP=1000\n",
    }
    forwards = FakeArchive(files)
    backwards = FakeArchive(files, reverse_listing=True)

    # When: both collections are merged.
    forward_records = merge_text_object_records(collect_text_object_records(forwards))
    backward_records = merge_text_object_records(collect_text_object_records(backwards))

    # Then: source-name ordering gives byte-for-byte stable records.
    assert repr(forward_records).encode() == repr(backward_records).encode()
    assert forward_records[0].fields["HP"] == "1000"


def test_collected_records_are_frozen_with_immutable_mappings() -> None:
    # Given: one valid trusted Strings record.
    archive = FakeArchive({"Units\\HumanUnitStrings.txt": b"[H001]\nName=Footman\n"})

    # When: a record is collected.
    record = collect_text_object_records(archive)[0]

    # Then: neither the record nor its mappings can be mutated.
    with pytest.raises(FrozenInstanceError):
        setattr(record, "obj_id", "H002")
    assert isinstance(record.fields, MappingProxyType)
    assert isinstance(record.field_sources, MappingProxyType)


def test_direct_records_copy_caller_mappings_and_expose_immutable_mappings() -> None:
    # Given: mutable mappings supplied to the public record constructor.
    fields = {"Name": "Footman"}
    field_sources = {"Name": "Units\\HumanUnitStrings.txt"}
    record = TextObjectRecord(
        category="unit",
        obj_id="H001",
        fields=fields,
        field_sources=field_sources,
        source_name="Units\\HumanUnitStrings.txt",
        source_kind=TextObjectSourceKind.STRINGS,
    )

    # When: the caller mutates its original mappings.
    fields["Name"] = "Knight"
    field_sources["Name"] = "changed"

    # Then: the record keeps the original values behind read-only mappings.
    assert record.fields["Name"] == "Footman"
    assert record.field_sources["Name"] == "Units\\HumanUnitStrings.txt"
    assert isinstance(record.fields, Mapping)
    assert isinstance(record.fields, MappingProxyType)
    assert isinstance(record.field_sources, MappingProxyType)


def test_anonymous_blocks_require_at_least_eight_objects() -> None:
    # Given: an anonymous block with seven object sections.
    payload = b"".join(
        f"[I{index:03d}]\nName=Item {index}\n".encode() for index in range(7)
    )
    archive = FakeAnonymousArchive((FakeBlock(payload),))

    # When: anonymous sources are collected.
    records = collect_text_object_records(archive)

    # Then: the existing minimum-object heuristic rejects the block.
    assert records == ()


def test_anonymous_blocks_at_threshold_are_collected() -> None:
    # Given: an anonymous block with eight object sections.
    payload = b"".join(
        f"[I{index:03d}]\nName=Item {index}\n".encode() for index in range(8)
    )
    archive = FakeAnonymousArchive((FakeBlock(payload),))

    # When: anonymous sources are collected.
    records = collect_text_object_records(archive)

    # Then: all threshold-qualified records are retained as anonymous.
    assert len(records) == 8
    assert {record.source_kind for record in records} == {
        TextObjectSourceKind.ANONYMOUS
    }


def test_malformed_or_oversized_trusted_sources_are_ignored() -> None:
    # Given: trusted files with no section syntax and content above the bounded parse limit.
    archive = FakeArchive(
        {
            "Units\\HumanUnitFunc.txt": b"not an object table",
            "Units\\OrcUnitStrings.txt": b"[O001]\nName=Grunt\n"
            + (b"x" * (5 * 1024 * 1024)),
        },
    )

    # When: the sources are collected.
    records = collect_text_object_records(archive)

    # Then: malformed and oversized content does not become a record.
    assert records == ()


def test_mixed_ability_strings_classifies_buff_section_separately() -> None:
    # Given: one trusted AbilityStrings file contains both an ability and its buff.
    archive = FakeArchive(
        {
            "Units\\HumanAbilityStrings.txt": (
                b"[A001]\nName=Flame\nOrder=flame\nTip=Cast flame\n"
                b"[B001]\nName=Burning\nTip=Burning\nUbertip=Damage over time\n"
            )
        }
    )

    # When: the mixed file is collected.
    records = collect_text_object_records(archive)

    # Then: category is selected per section, not once for the whole file.
    assert {(row.obj_id, row.category) for row in records} == {
        ("A001", "技能"),
        ("B001", "增益"),
    }
