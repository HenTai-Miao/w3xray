"""Regression coverage for Task 10 security review boundaries."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from w3xtool import archive_export, knowledge_unknown_exports, map_loader
from w3xtool.cli_options import CliOptions, _write_cli_packs
from w3xtool.load_context import MapLoadContext
from w3xtool.map_data import MapData
from w3xtool.mpq_files import list_archive_files


@dataclass(frozen=True, slots=True)
class _Block:
    file_pos: int
    comp_size: int = 1
    file_size: int = 1
    flags: int = 0


class _UnknownArchive:
    path = "fixture.w3x"
    archive_offset = 0
    _data = b"xxxxx"

    def __init__(self, blocks: tuple[_Block, ...]) -> None:
        self._blocks = blocks
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


class _OversizedListfileArchive:
    def __init__(self) -> None:
        self.read_calls = 0

    def has_file(self, name: str) -> bool:
        return name == "(listfile)"

    def declared_file_size(self, _name: str) -> int:
        return 8 * 1024 * 1024 + 1

    def read_file(self, _name: str) -> bytes:
        self.read_calls += 1
        raise AssertionError("oversized listfile was read")


class _OversizedCampaignArchive:
    path = "fixture.w3n"
    _data = b""
    child_name = "Maps\\Huge.w3x"

    def __init__(self) -> None:
        self.read_calls: list[str] = []

    def has_file(self, _name: str) -> bool:
        return False

    def list_files(self) -> list[str]:
        return [self.child_name]

    def declared_file_size(self, name: str) -> int | None:
        return 2 if name == self.child_name else None

    def read_file(self, name: str) -> bytes:
        self.read_calls.append(name)
        raise AssertionError("oversized campaign child was read")

    def close(self) -> None:
        return


def test_temp_cleanup_rejects_symlinked_extraction_base(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the predictable extraction base points outside the system temp root.
    temp_root = tmp_path / "temp"
    outside = tmp_path / "outside"
    target = outside / "Map"
    temp_root.mkdir()
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    _symlink_or_skip(temp_root / "w3xtool提取", outside)
    monkeypatch.setattr(archive_export.tempfile, "gettempdir", lambda: str(temp_root))

    # When: a fresh extraction directory is requested.
    result = Path(archive_export.tmp_extract_dir("Map", clean=True))

    # Then: it uses a new private root and leaves the predictable link untouched.
    assert marker.read_text(encoding="utf-8") == "keep"
    assert result.parent.name.startswith("w3xtool提取-")
    assert result.parent.parent == temp_root


def test_temp_cleanup_cannot_race_component_check_with_symlink_swap(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: the predictable base becomes a symlink immediately after its check.
    temp_root = tmp_path / "temp"
    outside = tmp_path / "outside"
    target = outside / "Map"
    temp_root.mkdir()
    target.mkdir(parents=True)
    marker = target / "keep.txt"
    marker.write_text("keep", encoding="utf-8")
    base = temp_root / "w3xtool提取"
    original_check = getattr(archive_export, "_reject_unsafe_temp_component", lambda _path: None)
    swapped = False

    def swap_after_check(path: str) -> None:
        nonlocal swapped
        original_check(path)
        if Path(path) == base and not swapped:
            swapped = True
            _symlink_or_skip(base, outside)

    monkeypatch.setattr(archive_export.tempfile, "gettempdir", lambda: str(temp_root))
    monkeypatch.setattr(
        archive_export,
        "_reject_unsafe_temp_component",
        swap_after_check,
        raising=False,
    )

    # When: cleanup proceeds after the attacker-controlled swap.
    result = Path(archive_export.tmp_extract_dir("Map", clean=True))

    # Then: the outside tree survives and the returned path remains in the temp root.
    assert marker.read_text(encoding="utf-8") == "keep"
    assert result.resolve().is_relative_to(temp_root.resolve())


def test_temp_extract_calls_use_distinct_private_roots(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: one system temporary directory.
    monkeypatch.setattr(archive_export.tempfile, "gettempdir", lambda: str(tmp_path))

    # When: the same map requests two extraction destinations.
    first = Path(archive_export.tmp_extract_dir("Map", clean=True))
    second = Path(archive_export.tmp_extract_dir("Map", clean=True))

    # Then: each call owns an independently created private root.
    assert first.parent != second.parent
    assert first.parent.name.startswith("w3xtool提取-")
    assert second.parent.name.startswith("w3xtool提取-")


def test_campaign_child_pack_stays_anchored_to_requested_root(tmp_path: Path) -> None:
    # Given: the child-pack directory inside a real pack root is a symlink.
    pack = tmp_path / "pack"
    outside = tmp_path / "outside"
    pack.mkdir()
    outside.mkdir()
    _symlink_or_skip(pack / "子地图", outside)
    parent = MapData("fixture.w3n", "Campaign")
    parent.sub_maps.append(MapData("Maps\\Child.w3x", "Child"))

    # When: CLI publication writes the parent and its loaded child.
    report = _write_cli_packs(parent, CliOptions("fixture.w3n", pack_dir=str(pack)), ())

    # Then: child writes fail inside the shared report without touching the target.
    assert report.failed_count > 0
    assert tuple(outside.iterdir()) == ()


def test_internal_listfile_size_is_checked_before_read() -> None:
    # Given: member metadata declares an internal listfile over the byte limit.
    archive = _OversizedListfileArchive()

    # When: known archive names are enumerated.
    _ = list_archive_files(archive)

    # Then: the oversized body is never decompressed or decoded.
    assert archive.read_calls == 0


def test_campaign_child_size_is_checked_before_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: one campaign child is larger than the entire remaining aggregate budget.
    archive = _OversizedCampaignArchive()
    monkeypatch.setattr(map_loader, "_MAX_CAMPAIGN_CHILD_BYTES", 1)

    # When: campaign extraction reaches that declared child.
    md = map_loader._load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    # Then: it is diagnosed without reading its body.
    assert archive.read_calls == []
    assert any(item.component == "campaign-child" for item in md.diagnostics)


def test_unknown_block_uses_remaining_budget_before_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: only one of two declared one-byte blocks fits the aggregate budget.
    archive = _UnknownArchive((_Block(0), _Block(1)))
    monkeypatch.setattr(knowledge_unknown_exports, "_MAX_UNKNOWN_EXPORT_BYTES", 1)

    # When: anonymous blocks are published.
    knowledge_unknown_exports.write_unknown_files_from_archive(archive, str(tmp_path))

    # Then: the second block is rejected before decompression.
    assert archive.read_indexes == [0]


def test_unknown_manifest_row_count_is_bounded(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    # Given: many blocks are rejected by the byte limit.
    archive = _UnknownArchive(tuple(_Block(index, file_size=2) for index in range(5)))
    monkeypatch.setattr(knowledge_unknown_exports, "_MAX_UNKNOWN_EXPORT_BYTES", 1)
    monkeypatch.setattr(
        knowledge_unknown_exports,
        "_MAX_UNKNOWN_MANIFEST_ROWS",
        2,
        raising=False,
    )

    # When: the manifest is generated.
    knowledge_unknown_exports.write_unknown_files_from_archive(archive, str(tmp_path))

    # Then: at most the configured number of data rows is retained.
    lines = (tmp_path / "Unknown_manifest.tsv").read_text(encoding="utf-8").splitlines()
    assert len(lines) == 3


def _symlink_or_skip(link: Path, target: Path) -> None:
    try:
        link.symlink_to(target, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
