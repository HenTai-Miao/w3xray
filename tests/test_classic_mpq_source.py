"""Layered classic Warcraft MPQ source tests."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from w3xtool.classic_mpq_source import ClassicMpqDataSource, classic_mpq_paths
from w3xtool.game_data_source import open_game_data_source, probe_game_data_path


class _FakeArchive:
    def __init__(self, files: dict[str, bytes]) -> None:
        self._files = {
            name.replace("/", "\\").casefold(): payload
            for name, payload in files.items()
        }
        self.close_count = 0

    def has_file(self, name: str) -> bool:
        return name.replace("/", "\\").casefold() in self._files

    def read_file(self, name: str) -> bytes:
        key = name.replace("/", "\\").casefold()
        if key not in self._files:
            raise KeyError(name)
        return self._files[key]

    def close(self) -> None:
        self.close_count += 1


def _factory(archives: dict[str, _FakeArchive]) -> Callable[[str], _FakeArchive]:
    return lambda path: archives[Path(path).name]


def test_classic_source_reads_the_highest_priority_archive(tmp_path: Path) -> None:
    # Given
    archives = {
        "War3Patch.mpq": _FakeArchive({"Units\\HumanUnitStrings.txt": b"patch"}),
        "War3x.mpq": _FakeArchive({"Units\\HumanUnitStrings.txt": b"expansion"}),
        "war3.mpq": _FakeArchive({"Units\\HumanUnitStrings.txt": b"base"}),
    }
    for name in archives:
        (tmp_path / name).touch()

    # When
    source = ClassicMpqDataSource(str(tmp_path), archive_factory=_factory(archives))

    # Then
    assert source.read_file("Units/HumanUnitStrings.txt") == b"patch"
    source.close()


def test_classic_source_reports_the_archive_that_supplied_a_member(
    tmp_path: Path,
) -> None:
    # Given
    archives = {
        "War3Patch.mpq": _FakeArchive({"Icons\\BTN.blp": b"patch"}),
        "war3.mpq": _FakeArchive({"Icons\\BTN.blp": b"base"}),
    }
    for name in archives:
        (tmp_path / name).touch()
    source = ClassicMpqDataSource(str(tmp_path), archive_factory=_factory(archives))

    # When
    payload, source_path = source.read_file_with_source("Icons/BTN.blp")

    # Then
    assert payload == b"patch"
    assert Path(source_path).name == "War3Patch.mpq"
    source.close()


def test_classic_paths_follow_documented_priority(tmp_path: Path) -> None:
    # Given
    for name in ("war3.mpq", "War3x.mpq", "War3xLocal.mpq", "War3Patch.mpq"):
        (tmp_path / name).touch()

    # When
    paths = classic_mpq_paths(str(tmp_path))

    # Then
    assert tuple(Path(path).name for path in paths) == (
        "War3Patch.mpq",
        "War3xLocal.mpq",
        "War3x.mpq",
        "war3.mpq",
    )


def test_classic_source_reports_a_missing_member(tmp_path: Path) -> None:
    # Given
    (tmp_path / "war3.mpq").touch()
    source = ClassicMpqDataSource(
        str(tmp_path),
        archive_factory=_factory({"war3.mpq": _FakeArchive({})}),
    )

    # When / Then
    with pytest.raises(FileNotFoundError, match="Missing.txt"):
        source.read_file("Units\\Missing.txt")
    source.close()


def test_classic_source_close_is_idempotent(tmp_path: Path) -> None:
    # Given
    (tmp_path / "war3.mpq").touch()
    archive = _FakeArchive({})
    source = ClassicMpqDataSource(
        str(tmp_path),
        archive_factory=_factory({"war3.mpq": archive}),
    )

    # When
    source.close()
    source.close()

    # Then
    assert archive.close_count == 1


def test_game_data_probe_prefers_classic_mpqs_over_generic_files(
    tmp_path: Path,
) -> None:
    # Given
    (tmp_path / "war3.mpq").write_bytes(b"container")

    # When
    probe = probe_game_data_path(str(tmp_path))

    # Then
    assert (probe.kind, probe.is_readable, probe.backend) == (
        "classic_mpq",
        True,
        "mpq",
    )


def test_open_classic_source_returns_none_for_an_invalid_archive(
    tmp_path: Path,
) -> None:
    # Given
    (tmp_path / "war3.mpq").write_bytes(b"not an MPQ")

    # When
    source = open_game_data_source(str(tmp_path))

    # Then
    assert source is None
