"""Release blockers at binary-map completeness boundaries."""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import struct
from typing import cast
import zlib

import pytest

from gametool.map_archive_reader import MapArchiveReader
from gametool.map_components import _add_preplaced, _add_w3i
from gametool.map_data import MapData
from gametool.mpq_block_reader import MPQBlockError, read_mpq_block
from gametool.mpq_constants import FLAG_COMPRESS, FLAG_EXISTS, FLAG_SINGLE_UNIT
from gametool.mpq_layout import ArchiveBytes, _Block
from gametool.w3obj import parse_object_data_report


@dataclass(frozen=True, slots=True)
class _Archive:
    files: dict[str, bytes]
    path: str = "release.w3x"
    _data: bytes = b""

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        pass


def _placement_header(count: int) -> bytes:
    return b"W3do" + struct.pack("<iii", 8, 11, count)


def _unit_record() -> bytes:
    record = b"hfoo" + struct.pack("<i7f", 0, 10, 20, 0, 0, 1, 1, 1)
    record += b"\0" + struct.pack("<i", 0) + b"\0\0"
    record += struct.pack(
        "<iiiiifiiiiiiiii", -1, -1, -1, 0, 0, 0, 1, 0, 0, 0, 0, 0, -1, -1, -1
    )
    return record + struct.pack("<i", 7)


def _doodad_record() -> bytes:
    return (
        b"LTlt"
        + struct.pack("<i7f", 0, 10, 20, 0, 0, 1, 1, 1)
        + bytes((2, 100))
        + struct.pack("<iii", -1, 0, 7)
    )


@pytest.mark.parametrize(
    "tail",
    (
        b"",
        struct.pack("<ii", 1, 0),
        struct.pack("<ii", 0, 1),
        struct.pack("<ii", 0, 0) + b"extra",
    ),
    ids=(
        "missing-tail",
        "unknown-tail-version",
        "truncated-special-record",
        "extra-bytes",
    ),
)
def test_doodad_tail_corruption_reaches_map_diagnostics(tail: bytes) -> None:
    archive = _Archive({"war3map.doo": _placement_header(1) + _doodad_record() + tail})
    md = MapData(archive.path, "release")

    _add_preplaced(md, cast(MapArchiveReader, archive))

    assert [obj.type_id for obj in md.doodads] == ["LTlt"]
    assert any(item.source == "war3map.doo" for item in md.diagnostics)


def test_unit_trailing_bytes_reach_map_diagnostics_without_losing_records() -> None:
    archive = _Archive(
        {"war3mapUnits.doo": _placement_header(1) + _unit_record() + b"extra"}
    )
    md = MapData(archive.path, "release")

    _add_preplaced(md, cast(MapArchiveReader, archive))

    assert [(obj.type_id, obj.x, obj.y) for obj in md.units] == [("hfoo", 10, 20)]
    assert any(item.source == "war3mapUnits.doo" for item in md.diagnostics)


def _w3i_with_force_name(name: bytes) -> bytes:
    header = struct.pack("<iii", 25, 1, 6060) + b"\0" * 4
    header += struct.pack("<8f4iiiI", *([0.0] * 8), *([0] * 4), 64, 64, 0) + b"L"
    header += struct.pack("<i", 0) + b"\0" * 4
    header += struct.pack("<i", 0) + b"\0" * 4
    header += struct.pack("<i3f4s", 0, 0, 0, 0, b"\0" * 4)
    header += b"none\0L" + b"\0" * 4
    return header + struct.pack("<iiII", 0, 1, 0, 1) + name


def test_unterminated_final_w3i_string_is_not_a_confirmed_force() -> None:
    archive = _Archive({"war3map.w3i": _w3i_with_force_name(b"unfinished")})
    md = MapData(archive.path, "release")

    _add_w3i(md, cast(MapArchiveReader, archive), {})

    assert md.w3i is not None
    assert md.w3i.forces == []
    assert md.w3i.parse_issue
    assert any(item.source == "war3map.w3i" for item in md.diagnostics)


def test_negative_object_modification_count_is_not_an_empty_complete_object() -> None:
    data = struct.pack("<ii", 2, 1) + b"hfoo\0\0\0\0" + struct.pack("<ii", -1, 0)

    report = parse_object_data_report(data, "w3u")

    assert report.objects == ()
    assert report.issues


@dataclass(slots=True)  # MUTABLE_OK: writable block-storage fixture.
class _BlockStorage:
    _data: ArchiveBytes
    archive_offset: int = 0
    sector_size: int = 128


@pytest.mark.parametrize("single_unit", (False, True))
def test_short_compressed_payload_does_not_become_success(single_unit: bool) -> None:
    payload = bytes((2,)) + zlib.compress(b"short")
    flags = FLAG_EXISTS | FLAG_COMPRESS
    if single_unit:
        flags |= FLAG_SINGLE_UNIT
        raw = payload
    else:
        raw = struct.pack("<II", 8, 8 + len(payload)) + payload
    block = _Block(0, len(raw), 128, flags)

    with pytest.raises(MPQBlockError, match="size|length|short"):
        read_mpq_block(_BlockStorage(raw), block, b"data", None)


def test_oversized_stored_sector_cannot_shift_the_next_sector() -> None:
    first, second = b"A" * 129, b"B" * 128
    raw = struct.pack("<III", 12, 12 + len(first), 12 + len(first) + len(second))
    raw += first + second
    block = _Block(0, len(raw), 256, FLAG_EXISTS | FLAG_COMPRESS)

    with pytest.raises(MPQBlockError, match="size|length"):
        read_mpq_block(_BlockStorage(raw), block, b"data", None)


def _copy_map(tmp_path: Path) -> Path:
    fixture = (
        Path(__file__).parent / "fixtures" / "reference" / "stormlib-huffman-map.w3x"
    )
    target = tmp_path / "source.w3x"
    target.write_bytes(fixture.read_bytes())
    return target


def test_map_load_rejects_source_replacement_before_delivery(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from gametool import map_loader

    path = _copy_map(tmp_path)
    original = path.read_bytes()
    real_load = map_loader._load_map_impl

    def load_then_replace(*args, **kwargs):
        md = real_load(*args, **kwargs)
        path.write_bytes(original[:-1] + bytes((original[-1] ^ 1,)))
        return md

    monkeypatch.setattr(map_loader, "_load_map_impl", load_then_replace)

    with pytest.raises(OSError, match="source|identity|changed"):
        map_loader.load_map(str(path))


@pytest.mark.parametrize("restore_mtime", (False, True))
def test_loaded_map_source_cannot_reopen_different_bytes(
    tmp_path: Path, restore_mtime: bool
) -> None:
    from gametool.map_loader import load_map

    path = _copy_map(tmp_path)
    md = load_map(str(path))
    try:
        before = path.stat()
        original = path.read_bytes()
        path.write_bytes(original[:-1] + bytes((original[-1] ^ 1,)))
        if restore_mtime:
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))
        assert md.archive_source is not None

        with pytest.raises(OSError, match="source|identity|changed"):
            with md.archive_source.open():
                pass
    finally:
        md.close()


@pytest.mark.parametrize("mapped", (False, True))
def test_fallback_copy_keeps_the_original_source_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, mapped: bool
) -> None:
    from gametool import mpq_storage
    from gametool.mpq import MPQArchive

    path = _copy_map(tmp_path)
    real_open = mpq_storage._open_path
    temporary_paths: list[str] = []

    def require_copy(path: str, *, temporary_path: str | None):
        if temporary_path is None:
            raise PermissionError("synthetic sharing denial")
        temporary_paths.append(temporary_path)
        return real_open(path, temporary_path=temporary_path)

    if mapped:
        monkeypatch.setattr(mpq_storage, "_MMAP_THRESHOLD", 1)
    monkeypatch.setattr(mpq_storage, "_open_path", require_copy)

    with MPQArchive(str(path)) as archive:
        assert archive.read_file("war3map.j")
        archive.verify_source()
        assert archive.source_identity is not None
        assert archive.source_identity.inode == path.stat().st_ino

    assert temporary_paths
    assert all(not Path(temporary).exists() for temporary in temporary_paths)


def test_payload_cache_pressure_keeps_other_decoded_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from gametool import mpq
    from gametool.mpq_names import HashEntry

    monkeypatch.setattr(mpq, "_PAYLOAD_CACHE_BUDGET", 6)
    archive = object.__new__(mpq.MPQArchive)
    archive._payload_cache = {(0, b"a"): b"aa", (1, b"b"): b"bb", (2, b"c"): b"cc"}
    archive._payload_cache_bytes = 6
    archive.block_table = [_Block(0, 0, 2, FLAG_EXISTS)] * 4
    monkeypatch.setattr(
        archive, "_resolve_match", lambda name: (HashEntry(0, 0, 0, 0, 3), name, b"d")
    )
    monkeypatch.setattr(archive, "_read_block", lambda *_args, **_kwargs: b"dd")

    assert archive.read_file("d") == b"dd"

    assert archive._payload_cache == {
        (1, b"b"): b"bb",
        (2, b"c"): b"cc",
        (3, b"d"): b"dd",
    }
    assert archive._payload_cache_bytes == 6
