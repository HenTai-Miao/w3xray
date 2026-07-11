"""Aggregate read budgets include failed parses and refused writes."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from w3xtool import (
    archive_export,
    archive_export_recovery,
    knowledge_unknown_exports,
    map_loader,
)
from w3xtool.load_context import MapLoadContext


class _CampaignArchive:
    path = "fixture.w3n"
    _data = b""
    child_names = ("Maps\\Bad1.w3x", "Maps\\Bad2.w3x")

    def __init__(self) -> None:
        self.read_calls: list[str] = []

    def has_file(self, _name: str) -> bool:
        return False

    def list_files(self) -> list[str]:
        return list(self.child_names)

    def declared_file_size(self, name: str) -> int | None:
        return 4 if name in self.child_names else None

    def read_file(self, name: str) -> bytes:
        self.read_calls.append(name)
        return b"bad!"

    def close(self) -> None:
        return


class _UnreadableCampaignArchive(_CampaignArchive):
    def read_file(self, name: str) -> bytes:
        self.read_calls.append(name)
        raise OSError("corrupt child member")


@dataclass(frozen=True, slots=True)
class _Block:
    file_pos: int
    comp_size: int = 1
    file_size: int = 1
    flags: int = 0


class _UnknownArchive:
    path = "fixture.w3x"
    archive_offset = 0
    _data = b"xx"

    def __init__(self) -> None:
        self._blocks = (_Block(0), _Block(1))
        self.read_indexes: list[int] = []

    def list_files(self) -> list[str]:
        return []

    def block_index_of(self, _name: str) -> int | None:
        return None

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self._blocks))

    def read_block_anon(self, block: _Block) -> bytes:
        self.read_indexes.append(self._blocks.index(block))
        return b"x"


class _NamedArchive:
    path = "fixture.w3x"
    archive_offset = 0
    _data = b""
    block_table: list[_Block] = []
    hash_table: list[tuple[int, int, int, int, int]] = []
    names = ("a.bin", "b.bin")

    def __init__(self) -> None:
        self.read_names: list[str] = []

    def list_files(self) -> list[str]:
        return list(self.names)

    def has_file(self, name: str) -> bool:
        return name in self.names

    def declared_file_size(self, name: str) -> int | None:
        return 1 if name in self.names else None

    def read_file(self, name: str) -> bytes:
        self.read_names.append(name)
        return b"x"

    def block_index_of(self, _name: str) -> int | None:
        return None

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return ()

    def read_block_anon(self, _block: _Block) -> bytes | None:
        return None


class _FailingNamedArchive(_NamedArchive):
    def read_file(self, name: str) -> bytes:
        self.read_names.append(name)
        raise OSError("corrupt member")


class _UnknownFallbackArchive(_NamedArchive):
    names: tuple[str, ...] = ()

    def __init__(self) -> None:
        super().__init__()
        self._blocks = (
            _Block(0, comp_size=0, file_size=1),
            _Block(0, comp_size=0, file_size=1),
        )
        self.read_indexes: list[int] = []

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self._blocks))

    def read_block_anon(self, block: _Block) -> bytes | None:
        self.read_indexes.append(self._blocks.index(block))
        return None


class _RecoveredArchive:
    path = "fixture.w3x"

    def __init__(self, file_sizes: tuple[int, ...]) -> None:
        self.names = tuple(f"asset{index}.bin" for index in range(len(file_sizes)))
        self.block_table = [
            _Block(index, file_size=file_size)
            for index, file_size in enumerate(file_sizes)
        ]
        self.hash_table = [
            (
                archive_export_recovery._hash(name, archive_export_recovery.HASH_NAME_A),
                archive_export_recovery._hash(name, archive_export_recovery.HASH_NAME_B),
                0,
                0,
                index,
            )
            for index, name in enumerate(self.names)
        ]
        self.read_names: list[str] = []

    def list_files(self) -> list[str]:
        return list(self.names)

    def read_file(self, name: str) -> bytes:
        self.read_names.append(name)
        return b"x"

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return ()

    def read_block_anon(self, _block: _Block) -> bytes | None:
        return None


class _RecoveryScanArchive(_RecoveredArchive):
    def __init__(self) -> None:
        super().__init__((1, 1))
        self.hash_table = []
        self.read_indexes: list[int] = []

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self.block_table))

    def read_block_anon(self, block: _Block) -> bytes | None:
        self.read_indexes.append(self.block_table.index(block))
        return None


class _OversizedUnknownArchive(_UnknownArchive):
    def read_block_anon(self, block: _Block) -> bytes:
        self.read_indexes.append(self._blocks.index(block))
        return b"xx"


def test_failed_campaign_parse_still_consumes_read_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: only one malformed child fits the campaign decompression budget.
    archive = _CampaignArchive()
    monkeypatch.setattr(map_loader, "_MAX_CAMPAIGN_READ_BYTES", 4, raising=False)

    # When: both declared children are considered.
    md = map_loader._load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the first failed parse is charged and the second body is not read.
    assert archive.read_calls == [archive.child_names[0]]
    assert md.sub_maps == []


def test_failed_campaign_read_still_consumes_declared_budget(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: only one unreadable child's declared size fits the read budget.
    archive = _UnreadableCampaignArchive()
    monkeypatch.setattr(map_loader, "_MAX_CAMPAIGN_READ_BYTES", 4, raising=False)

    # When: campaign loading reaches two unreadable declared children.
    md = map_loader._load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: the first failed read remains charged and the second is not attempted.
    assert archive.read_calls == [archive.child_names[0]]
    assert md.sub_maps == []


def test_refused_unknown_write_still_consumes_read_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the output directory is unsafe, but only one block fits the read budget.
    root = tmp_path / "pack"
    outside = tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    try:
        (root / "Unknown").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    archive = _UnknownArchive()
    monkeypatch.setattr(knowledge_unknown_exports, "_MAX_UNKNOWN_EXPORT_BYTES", 1)

    # When: anonymous publication refuses the first destination.
    knowledge_unknown_exports.write_unknown_files_from_archive(archive, str(root))

    # Then: the refused write cannot reset the decompression budget.
    assert archive.read_indexes == [0]
    assert tuple(outside.iterdir()) == ()


def test_refused_named_write_still_consumes_read_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the complete-extraction root is unsafe and only one member fits.
    outside = tmp_path / "outside"
    outside.mkdir()
    output = tmp_path / "output"
    try:
        output.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
    archive = _NamedArchive()
    monkeypatch.setattr(archive_export, "_MAX_NAMED_EXPORT_BYTES", 1)

    # When: full extraction refuses the first named destination.
    archive_export._export_all_impl(archive, str(output), 1)

    # Then: the refused write still prevents a second member read.
    assert archive.read_names == [archive.names[0]]
    assert tuple(outside.iterdir()) == ()


def test_failed_named_read_still_consumes_read_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: two corrupt named members each declare one byte and only one fits.
    archive = _FailingNamedArchive()
    monkeypatch.setattr(archive_export, "_MAX_NAMED_EXPORT_BYTES", 1)

    # When: complete extraction attempts the corrupt members.
    archive_export._export_all_impl(archive, str(tmp_path), 1)

    # Then: the failed first read consumes the budget before the second member.
    assert archive.read_names == [archive.names[0]]


def test_unknown_raw_fallback_charges_declared_attempt_size(tmp_path: Path) -> None:
    # Given: anonymous decode falls back to empty raw bodies but declares one byte each.
    archive = _UnknownFallbackArchive()

    # When: only one declared output byte is available to full extraction.
    archive_export._export_unknown_blocks(
        archive,
        str(tmp_path),
        set(),
        [],
        [],
        1,
    )

    # Then: the first decode attempt consumes the budget despite an empty raw body.
    assert archive.read_indexes == [0]


def test_recovered_name_budget_stops_reads_after_first_member(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: two recovered names each declare one byte and only one byte is allowed.
    archive = _RecoveredArchive((1, 1))
    monkeypatch.setattr(archive_export_recovery, "_MAX_RECOVERY_EXPORT_BYTES", 1)

    # When: recovered-name export reaches the aggregate byte budget.
    count = archive_export_recovery._export_recovered_named_files(
        archive,
        str(tmp_path),
        set(),
    )

    # Then: the second member is rejected before another archive read.
    assert count == 1
    assert archive.read_names == [archive.names[0]]


def test_recovered_name_declared_size_is_checked_before_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: one recovered member declares more bytes than the complete budget.
    archive = _RecoveredArchive((2,))
    monkeypatch.setattr(archive_export_recovery, "_MAX_RECOVERY_EXPORT_BYTES", 1)

    # When: recovered-name export considers that hash-table entry.
    count = archive_export_recovery._export_recovered_named_files(
        archive,
        str(tmp_path),
        set(),
    )

    # Then: no decompression/read is attempted for the oversized member.
    assert count == 0
    assert archive.read_names == []


def test_recovery_scan_failed_read_still_consumes_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: anonymous scan attempts return no data and only one declared byte fits.
    archive = _RecoveryScanArchive()
    monkeypatch.setattr(archive_export_recovery, "_MAX_RECOVERY_SCAN_BYTES", 1)

    # When: name recovery scans blocks for embedded resource paths.
    archive_export_recovery._export_recovered_named_files(archive, str(tmp_path), set())

    # Then: a failed first attempt still prevents a second decompression attempt.
    assert archive.read_indexes == [0]


def test_oversized_unknown_read_still_consumes_budget(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: blocks underreport one byte but each expands beyond the one-byte budget.
    archive = _OversizedUnknownArchive()
    monkeypatch.setattr(knowledge_unknown_exports, "_MAX_UNKNOWN_EXPORT_BYTES", 1)

    # When: the first anonymous block exceeds the remaining budget after reading.
    knowledge_unknown_exports.write_unknown_files_from_archive(archive, str(tmp_path))

    # Then: the oversized result is charged and no second block is decompressed.
    assert archive.read_indexes == [0]
