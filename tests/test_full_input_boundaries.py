"""Complete input coverage, stable reads, and new static-query capabilities."""

from __future__ import annotations

import ctypes
import json
import os
from pathlib import Path
import stat
import struct
from types import SimpleNamespace
from typing import cast

import pytest

from gametool import bounded_file
from gametool import casclib_api
from gametool import description_cache_retained_tree_snapshot as trees
from gametool import pack_query_cli as queries
from gametool.blp import decode_blp
from gametool.bounded_file import (
    BoundedFileError,
    read_bounded_regular_file,
    sha256_regular_file,
)
from gametool.live_handle_chain import (
    MemoryReader,
    HandleSystem,
    selected_unit,
    selected_units,
    _looks_like_handle_manager,
)
from gametool.live_object_dump import extract_registered_records, parse_slk_blocks
from gametool.memory_regions import contiguous_regions
from gametool.pack_query_placements import script_placements
from tests.test_blp import _build_blp2_palette
from tests.test_casclib_api import FakeNativeLibrary
from tests.test_live_handle_chain import DLL_BASE, _build_memory
from tests.test_live_selection_complete import _selection_memory


def test_unrestricted_file_read_still_uses_small_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(bounded_file, "_READ_CHUNK_BYTES", 3)
    path = tmp_path / "input.bin"
    path.write_bytes(b"complete data and tail")
    content, identity = read_bounded_regular_file(path)
    assert content == b"complete data and tail"
    assert identity.size == len(content)


@pytest.mark.parametrize("hashing", [False, True])
def test_regular_file_change_during_read_is_rejected(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, hashing: bool
) -> None:
    path = tmp_path / "input.bin"
    path.write_bytes(b"a" * 32)
    before = path.stat()
    original = bounded_file.os.read
    changed = False

    def read_then_change(descriptor: int, count: int) -> bytes:
        nonlocal changed
        chunk = original(descriptor, count)
        if chunk and not changed:
            changed = True
            os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns + 1_000_000_000))
        return chunk

    monkeypatch.setattr(bounded_file.os, "read", read_then_change)
    with pytest.raises(BoundedFileError, match="changed"):
        if hashing:
            sha256_regular_file(path)
        else:
            read_bounded_regular_file(path)


def test_retained_tree_has_no_recursion_or_depth_ceiling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    depth = 1500
    closed: list[int] = []

    def details(index: int, *, file: bool = False) -> os.stat_result:
        return cast(
            os.stat_result,
            cast(
                object,
                SimpleNamespace(
                    st_dev=1,
                    st_ino=index + 1,
                    st_size=7 if file else 0,
                    st_mtime_ns=1,
                    st_ctime_ns=1,
                    st_mode=(stat.S_IFREG if file else stat.S_IFDIR) | 0o700,
                ),
            ),
        )

    def named(_name: str, *, dir_fd: int, follow_symlinks: bool) -> os.stat_result:
        assert not follow_symlinks
        return details(dir_fd + 1, file=dir_fd == depth)

    fake = SimpleNamespace(
        fstat=lambda descriptor: details(descriptor),
        listdir=lambda descriptor: ["d" if descriptor < depth else "tail"],
        stat=named,
        open=lambda _name, _flags, *, dir_fd: dir_fd + 1,
        close=lambda descriptor: closed.append(descriptor),
    )
    monkeypatch.setattr(trees, "os", fake)
    monkeypatch.setattr(trees, "directory_read_flags", lambda: 0)
    snapshot = trees.snapshot_retained_tree(0, trees.RetainedScanBounds())
    assert snapshot.status is trees.TreeProofStatus.COMPLETE
    assert snapshot.file_count == 1 and snapshot.size == 7
    assert snapshot.entry_count == depth + 1
    assert snapshot.entries[-1].relative_path.endswith("/tail")
    assert closed == list(range(depth, 0, -1))


def test_casc_64_bit_size_is_not_rejected_at_two_gib() -> None:
    dll = FakeNativeLibrary()

    def large_size(_handle: object, output) -> bool:
        output._obj.value = 3 * 1024**3
        return True

    dll.CascGetFileSize64.callback = large_size
    api = casclib_api.CtypesCascLibApi(library=dll)  # pyright: ignore[reportArgumentType]
    assert api.file_size(202) == 3 * 1024**3


def test_casc_reads_all_native_chunks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(casclib_api, "_READ_CHUNK_BYTES", 3)
    dll = FakeNativeLibrary()
    payload = b"full data tail"
    offset = 0
    requests: list[int] = []

    def read(_handle: object, buffer, size: int, bytes_read) -> bool:
        nonlocal offset
        chunk = payload[offset : offset + size]
        ctypes.memmove(buffer, chunk, len(chunk))
        bytes_read._obj.value = len(chunk)
        offset += len(chunk)
        requests.append(size)
        return True

    dll.CascReadFile.callback = read
    api = casclib_api.CtypesCascLibApi(library=dll)  # pyright: ignore[reportArgumentType]
    assert api.read_file(202, len(payload)) == payload
    assert requests == [3, 3, 3, 3, 2]


def test_blp_width_above_former_ceiling_uses_encoded_pixels() -> None:
    width = 16385
    image = decode_blp(_build_blp2_palette(width, 1, [(1, 2, 3, 255)], [0] * width))
    assert image is not None and image.size == (width, 1)
    assert image.getpixel((width - 1, 0)) == (3, 2, 1, 255)


@pytest.mark.parametrize(
    ("depth", "packed", "expected"),
    [(1, [0b1101], [255, 0, 255, 255]), (4, [0xA1, 0xF0], [17, 170, 0, 255])],
)
def test_blp_packed_alpha_is_preserved(
    depth: int, packed: list[int], expected: list[int]
) -> None:
    data = bytearray(_build_blp2_palette(4, 1, [(1, 2, 3, 255)], [0] * 4, alpha=packed))
    data[9] = depth
    image = decode_blp(bytes(data))
    assert image is not None
    assert list(image.getchannel("A").tobytes()) == expected


def test_static_coordinates_cover_arithmetic_location_and_skin_calls() -> None:
    source = (
        "call CreateUnitAtLoc(Player(0),'n001',Location(128*2,-(32+4)),0)\n"
        "call BlzCreateUnitWithSkin(Player(0),'n002',10/2,2**3,0,'n002')\n"
        "call CreateItemLoc('I001',Location(8%3,20-3))\n"
        "call BlzCreateItemWithSkin('I002',2+4,3*3,'I002')\n"
        "call CreateItem('IBAD',__import__('os').getpid(),0)\n"
    )
    assert script_placements(source) == [
        ("n001", 256.0, -36.0, "unit"),
        ("n002", 5.0, 8.0, "unit"),
        ("I001", 2.0, 17.0, "item"),
        ("I002", 6.0, 9.0, "item"),
    ]
    assert script_placements(
        'local x=8//3; CreateItem(FourCC("I003"),8//3,2^3)', lua=True
    ) == [("I003", 2.0, 8.0, "item")]


def test_query_warning_only_reports_sources_used_in_that_query(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(queries, "_memo_dir", lambda: tmp_path / "memo")
    monkeypatch.setattr(queries, "_LOCKED_FILES", set())
    bad_path = tmp_path / "bad.tsv"
    bad_path.write_bytes(b"content")
    original_open = Path.open

    def denied(path: Path, *args, **kwargs):
        if path == bad_path:
            raise PermissionError("temporary lock")
        return original_open(path, *args, **kwargs)

    with monkeypatch.context() as scoped:
        scoped.setattr(Path, "open", denied)
        scoped.setattr(queries.time, "sleep", lambda _delay: None)
        bad = queries.execute_pack_query(
            queries.PackQueryCliOptions(str(tmp_path), "text", "missing")
        )
    assert any("bad.tsv" in note for note in bad.diagnostics)
    clean = queries.execute_pack_query(
        queries.PackQueryCliOptions(str(tmp_path), "item", "missing")
    )
    assert not any("bad.tsv" in note for note in clean.diagnostics)


def test_adjacent_memory_ranges_preserve_split_json_and_object_fields() -> None:
    info = json.dumps({"name": "Complete", "params": ["x" * 5000, 9]})
    message = json.dumps({"page": 1, "info": info}).encode()
    chunks = [(100, message[:17]), (117, message[17:] + b"\x00")]
    assert extract_registered_records(chunks)["Complete"]["records"] == [
        ["x" * 5000, 9]
    ]
    key = "k" * 100
    block = b"\n\r\n[I001\x00\n" + key.encode() + b"\x00last\x00\n"
    objects, _duplicates = parse_slk_blocks([(100, block[:13]), (113, block[13:])])
    assert objects["I001"][key] == "last"
    assert list(contiguous_regions([(0, b"ab"), (3, b"de")])) == [
        (0, b"ab"),
        (3, b"de"),
    ]
    assert MemoryReader([(100, b"ab"), (102, b"cd")]).read(101, 3) == b"bcd"


def test_native_selection_reaches_tail_and_stops_on_cycles() -> None:
    # Keep the confirmed unit after the former twelve-node ceiling. Earlier
    # unreadable unit pointers must not erase it, and a physical cycle must stop.
    handles = [(0x80000100 + index, 0x6000 + index) for index in range(19)]
    handles.append((0x80000007, 0x5001))
    data, _reader, _system, hero, _other, offsets = _selection_memory(
        handles, cycle=True
    )
    manager = bytearray(data[0x1B600000])
    struct.pack_into("<I", manager, offsets.sel_entry_off, hero)
    data[0x1B600000] = bytes(manager)
    reader = MemoryReader(list(data.items()))
    system = HandleSystem(reader, DLL_BASE, offsets)
    selection = selected_units(reader, system, offsets, DLL_BASE)
    assert [unit.unit_addr for unit in selection.units] == [hero]
    assert len(selection.entries) == 20 and selection.entries[-1].unit_address == hero
    assert selection.entries[-1].raw_node_bytes is not None
    assert not selection.complete
    assert any("循环" in note for note in selection.diagnostics)

    # The primary field is independent of all collection nodes. The legacy
    # walk argument must never turn the unit's vtable into a list successor.
    primary = selected_unit(reader, system, offsets, DLL_BASE, max_walk=12)
    assert primary is not None and primary.unit_addr == hero
    invalid_primary = bytearray(data[hero])
    struct.pack_into("<II", invalid_primary, offsets.entry_pair_off, 0, 0)
    data[hero] = bytes(invalid_primary)
    empty_reader = MemoryReader(list(data.items()))
    assert (
        selected_unit(
            empty_reader,
            HandleSystem(empty_reader, DLL_BASE, offsets),
            offsets,
            DLL_BASE,
        )
        is None
    )


def test_handle_manager_validation_finds_live_entries_after_slot_128() -> None:
    regions, _hero, _other, offsets = _build_memory()
    changed: list[tuple[int, bytes]] = []
    for base, original in regions:
        data = bytearray(original)
        if base == 0x40000000:
            data = bytearray(160 * 8)
            data[150 * 8 : 152 * 8] = original[0x11 * 8 : 0x13 * 8]
        elif base == 0x40010000:
            data = bytearray(len(data))
        elif base == 0x1B3A0000:
            struct.pack_into("<I", data, offsets.hm_tableA_bound_off, 160)
        changed.append((base, bytes(data)))
    assert _looks_like_handle_manager(MemoryReader(changed), 0x1B3A0000, offsets)
