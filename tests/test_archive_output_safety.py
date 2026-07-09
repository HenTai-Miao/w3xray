"""Archive extraction sinks reject symlinked output components."""

from __future__ import annotations

from pathlib import Path

import pytest

from w3xtool.api import _export_all_impl, _export_recovered_named_files
from w3xtool.mpq import FLAG_EXISTS, HASH_NAME_A, HASH_NAME_B, _Block, _hash


class _NamedArchive:
    block_table: list[_Block] = []
    hash_table: list[tuple[int, int, int, int, int]] = []
    path = "fixture.w3x"
    archive_offset = 0
    _data = b""

    def list_files(self) -> list[str]:
        return [r"Assets\Panel.blp"]

    def has_file(self, name: str) -> bool:
        return name == r"Assets\Panel.blp"

    def read_file(self, name: str) -> bytes:
        if not self.has_file(name):
            raise KeyError(name)
        return b"BLP1panel"

    def block_index_of(self, _name: str) -> int | None:
        return None

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return ()

    def read_block_anon(self, _block: _Block) -> bytes | None:
        return None


class _AnonymousArchive(_NamedArchive):
    block = _Block(file_pos=0, comp_size=4, file_size=4, flags=FLAG_EXISTS)
    _data = b"BLP1"

    def list_files(self) -> list[str]:
        return []

    def has_file(self, _name: str) -> bool:
        return False

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return ((0, self.block),)

    def read_block_anon(self, _block: _Block) -> bytes | None:
        return b"BLP1"


class _RawArchive(_AnonymousArchive):
    def read_block_anon(self, _block: _Block) -> bytes | None:
        return None


def test_named_archive_file_does_not_follow_in_root_parent_symlink(tmp_path: Path) -> None:
    output = tmp_path / "out"
    actual = output / "actual"
    actual.mkdir(parents=True)
    _symlink(output / "Assets", actual, directory=True)

    _export_all_impl(_NamedArchive(), str(output), 1)

    assert not (actual / "Panel.blp").exists()


def test_anonymous_archive_file_does_not_follow_directory_symlink(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(output / "Unknown", outside, directory=True)

    _export_all_impl(_AnonymousArchive(), str(output), 1)

    assert not (outside / "File000000.blp").exists()


def test_raw_archive_file_and_manifest_do_not_follow_directory_symlink(tmp_path: Path) -> None:
    output = tmp_path / "out"
    output.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    _symlink(output / "UnknownRaw", outside, directory=True)

    _export_all_impl(_RawArchive(), str(output), 1)

    assert not (outside / "File000000.mpqraw").exists()
    assert not (outside / "manifest.tsv").exists()


def test_recovered_name_does_not_follow_destination_symlink(tmp_path: Path) -> None:
    model = _Block(file_pos=0, comp_size=1, file_size=1, flags=FLAG_EXISTS)
    texture = _Block(file_pos=1, comp_size=1, file_size=1, flags=FLAG_EXISTS)
    name = r"Textures\foo.blp"

    class Archive:
        block_table = [model, texture]
        hash_table = [(_hash(name, HASH_NAME_A), _hash(name, HASH_NAME_B), 0, 0, 1)]

        def list_files(self) -> list[str]:
            return []

        def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
            return ((0, model), (1, texture))

        def read_block_anon(self, block: _Block) -> bytes | None:
            if block is model:
                return b"MDLX\x00Textures\\foo.blp\x00"
            return b"BLP1texture"

        def read_file(self, file_name: str) -> bytes:
            if file_name != name:
                raise KeyError(file_name)
            return b"BLP1texture"

    output = tmp_path / "out"
    textures = output / "Textures"
    textures.mkdir(parents=True)
    target = output / "target.blp"
    target.write_bytes(b"before")
    _symlink(textures / "foo.blp", target)

    count = _export_recovered_named_files(Archive(), str(output), set())

    assert count == 0
    assert target.read_bytes() == b"before"


def test_recovered_unc_name_is_rejected_before_normalization(tmp_path: Path) -> None:
    model = _Block(file_pos=0, comp_size=1, file_size=1, flags=FLAG_EXISTS)
    texture = _Block(file_pos=1, comp_size=1, file_size=1, flags=FLAG_EXISTS)
    raw_name = r"\\server\share\evil.blp"
    normalized_name = r"server\share\evil.blp"

    class Archive:
        block_table = [model, texture]
        hash_table = [
            (
                _hash(normalized_name, HASH_NAME_A),
                _hash(normalized_name, HASH_NAME_B),
                0,
                0,
                1,
            ),
        ]

        def list_files(self) -> list[str]:
            return []

        def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
            return ((0, model), (1, texture))

        def read_block_anon(self, block: _Block) -> bytes | None:
            if block is model:
                return b"MDLX\x00" + raw_name.encode() + b"\x00"
            return b"BLP1texture"

        def read_file(self, file_name: str) -> bytes:
            if file_name != normalized_name:
                raise KeyError(file_name)
            return b"BLP1texture"

    output = tmp_path / "out"

    count = _export_recovered_named_files(Archive(), str(output), set())

    assert count == 0
    assert not (output / "server" / "share" / "evil.blp").exists()


def _symlink(link: Path, target: Path, *, directory: bool = False) -> None:
    try:
        link.symlink_to(target, target_is_directory=directory)
    except OSError as exc:
        pytest.skip(f"symlink unavailable: {exc}")
