"""Passive image identification uses declared PE structures and bounded APIs."""

from __future__ import annotations

import ctypes
from dataclasses import asdict, replace
import struct
from types import SimpleNamespace

import pytest

from gametool import live_inventory as live
from gametool import live_pe_image as pe
from gametool.live_handle_chain import ProfileFingerprint


def pe_fixture(*, machine=0x14C, versions=((1, 27, 0, 52240),), pe_offset=0x80):
    """Build an inert PE with one resource section and every declared language."""
    optional_size = 240 if machine in (0x8664, 0xAA64) else 224
    headers_size = (pe_offset + 24 + optional_size + 40 + 511) & ~511
    resource_rva = (headers_size + 4095) & ~4095
    image_size = resource_rva + 0x1000
    data = bytearray(headers_size + 0x400)
    data[:2] = b"MZ"
    struct.pack_into("<I", data, 0x3C, pe_offset)
    data[pe_offset : pe_offset + 4] = b"PE\0\0"
    struct.pack_into("<HHI", data, pe_offset + 4, machine, 1, 0x12345678)
    struct.pack_into("<H", data, pe_offset + 20, optional_size)
    optional = pe_offset + 24
    is_64 = optional_size == 240
    struct.pack_into("<H", data, optional, 0x20B if is_64 else 0x10B)
    struct.pack_into("<II", data, optional + 56, image_size, headers_size)
    directories = optional + (112 if is_64 else 96)
    struct.pack_into("<I", data, directories - 4, 16)
    struct.pack_into("<II", data, directories + 16, resource_rva, 0x400)
    section = optional + optional_size
    data[section : section + 8] = b".rsrc\0\0\0"
    struct.pack_into(
        "<IIII", data, section + 8, 0x400, resource_rva, 0x400, headers_size
    )
    root = headers_size
    struct.pack_into("<HHII", data, root + 12, 0, 1, 16, 0x80000020)
    struct.pack_into("<HHII", data, root + 0x2C, 0, 1, 1, 0x80000040)
    struct.pack_into("<HH", data, root + 0x4C, 0, len(versions))
    for index, version in enumerate(versions):
        data_offset = 0x80 + 16 * index
        payload_offset = 0x100 + 0x80 * index
        payload = bytearray(struct.pack("<HHH", 0, 52, 0))
        payload.extend("VS_VERSION_INFO\0".encode("utf-16-le"))
        payload.extend(bytes((-len(payload)) % 4))
        payload.extend(
            struct.pack(
                "<13I",
                0xFEEF04BD,
                0x10000,
                (version[0] << 16) | version[1],
                (version[2] << 16) | version[3],
                *([0] * 9),
            )
        )
        struct.pack_into("<H", payload, 0, len(payload))
        struct.pack_into(
            "<II", data, root + 0x50 + 8 * index, 1033 + index, data_offset
        )
        struct.pack_into(
            "<IIII",
            data,
            root + data_offset,
            resource_rva + payload_offset,
            len(payload),
            0,
            0,
        )
        data[root + payload_offset : root + payload_offset + len(payload)] = payload
    loaded = bytearray(image_size)
    loaded[:headers_size] = data[:headers_size]
    loaded[resource_rva : resource_rva + 0x400] = data[root:]
    return (
        bytes(data),
        bytes(loaded),
        ProfileFingerprint(machine, 0x12345678, image_size),
    )


def snapshot_image(base, fingerprint=None):
    """Return real encoded headers and the identification that precedes a snapshot."""
    encoded, _loaded, default = pe_fixture()
    fingerprint = fingerprint or default
    encoded = bytearray(encoded)
    struct.pack_into("<H", encoded, 0x84, fingerprint.machine)
    struct.pack_into("<I", encoded, 0x88, fingerprint.timestamp)
    struct.pack_into("<I", encoded, 0x98 + 56, fingerprint.image_size)
    header = pe.parse_pe_image(bytes(encoded)).header
    assert header is not None
    return bytes(encoded[: header.headers_size]), {
        "game_dll": {"base": base, "size": header.image_size},
        "image_verified": True,
        "image_fingerprint": asdict(fingerprint),
        "image_header": pe.pe_header_record(header),
    }


@pytest.mark.parametrize("machine", [0x14C, 0x8664])
@pytest.mark.parametrize("pe_offset", [0x80, 0x11000])
def test_version_comes_from_declared_resource_without_header_window(
    machine, pe_offset, tmp_path
):
    data, _loaded, fingerprint = pe_fixture(machine=machine, pe_offset=pe_offset)
    path = tmp_path / "inert.dll"
    path.write_bytes(data)
    assert live.read_file_version(path) == "1.27.0.52240"
    assert live.pe_machine(path) == machine
    assert live.read_pe_fingerprint(path) == fingerprint


@pytest.mark.parametrize(
    "data",
    [
        b"arbitrary 1.27.0.52240 text",
        b"padding" + struct.pack("<6I", 0xFEEF04BD, 0x10000, 0x1001B, 52240, 0, 0),
    ],
)
def test_arbitrary_text_and_fixed_info_magic_are_not_a_version(data, tmp_path):
    path = tmp_path / "Game.dll"
    path.write_bytes(data)
    assert live.read_file_version(path) is None
    assert live.read_pe_fingerprint(path) is None
    assert live.pe_machine(path) == 0


@pytest.mark.parametrize(
    "mutation",
    [
        "mz",
        "signature",
        "magic",
        "machine",
        "optional_size",
        "sections",
        "raw_truncated",
    ],
)
def test_malformed_pe_headers_never_supply_architecture(mutation):
    data, _loaded, _fingerprint = pe_fixture()
    data = bytearray(data)
    if mutation == "mz":
        data[:2] = b"ZZ"
    elif mutation == "signature":
        data[0x80:0x84] = b"NOPE"
    elif mutation == "magic":
        struct.pack_into("<H", data, 0x98, 0)
    elif mutation == "machine":
        struct.pack_into("<H", data, 0x84, 0x8664)
    elif mutation == "optional_size":
        struct.pack_into("<H", data, 0x94, 32)
    elif mutation == "sections":
        struct.pack_into("<H", data, 0x86, 65535)
    else:
        del data[-1:]
    result = pe.parse_pe_image(bytes(data))
    assert result.header is None and result.version is None and result.diagnostics


@pytest.mark.parametrize(
    "mutation",
    [
        "type",
        "cycle",
        "count",
        "rva",
        "key",
        "fixed_size",
        "fixed_signature",
        "root_length",
    ],
)
def test_invalid_resource_keeps_header_but_never_guesses_version(mutation):
    data, _loaded, _fingerprint = pe_fixture()
    data = bytearray(data)
    root = 0x200
    if mutation == "type":
        struct.pack_into("<I", data, root + 16, 15)
    elif mutation == "cycle":
        struct.pack_into("<I", data, root + 0x34, 0x80000020)
    elif mutation == "count":
        struct.pack_into("<H", data, root + 14, 65535)
    elif mutation == "rva":
        struct.pack_into("<I", data, root + 0x80, 0x70000000)
    elif mutation == "key":
        data[root + 0x106] = ord("X")
    elif mutation == "fixed_size":
        struct.pack_into("<H", data, root + 0x102, 51)
    elif mutation == "fixed_signature":
        data[root + 0x128] = 0
    else:
        struct.pack_into("<H", data, root + 0x100, 65535)
    result = pe.parse_pe_image(bytes(data))
    assert result.header is not None and result.version is None and result.diagnostics


def test_all_version_languages_must_agree():
    first = (1, 27, 0, 52240)
    assert (
        pe.parse_pe_image(pe_fixture(versions=(first, first))[0]).version
        == "1.27.0.52240"
    )
    conflict = pe.parse_pe_image(pe_fixture(versions=(first, (3, 0, 0, 24268)))[0])
    assert conflict.version is None and "冲突" in conflict.diagnostics[0]


def test_same_snapshot_is_required_for_version_and_metadata(monkeypatch, tmp_path):
    path = tmp_path / "inert.exe"
    path.write_bytes(pe_fixture()[0])
    fstat = pe.os.fstat
    calls = 0

    def changed_stat(fd):
        nonlocal calls
        calls += 1
        actual = fstat(fd)
        return SimpleNamespace(
            **{
                name: getattr(actual, name)
                + (1 if calls == 2 and name == "st_mtime_ns" else 0)
                for name in (
                    "st_dev",
                    "st_ino",
                    "st_size",
                    "st_mtime_ns",
                    "st_ctime_ns",
                )
            }
        )

    monkeypatch.setattr(pe.os, "fstat", changed_stat)
    result = pe.read_pe_image(path)
    assert result.header is None and result.version is None
    assert "变化" in result.diagnostics[0]


class NativeCall:
    def __init__(self, call):
        self.call = call

    def __call__(self, *args):
        return self.call(*args)


def native_modules(
    monkeypatch, counts, *, fail_after=None, missing_path=None, long_name=False
):
    calls = []
    sequence = iter(counts)
    pointer_bytes = ctypes.sizeof(ctypes.c_void_p)

    def enumerate_modules(_handle, array, capacity, needed, *_flags):
        calls.append(capacity)
        if fail_after is not None and len(calls) > fail_after:
            return 0
        count = next(sequence)
        needed._obj.value = count * pointer_bytes
        if array is not None:
            for index in range(min(count, capacity // pointer_bytes)):
                array[index] = 0x100000 + index * 0x1000
        return 1

    def module_path(_handle, base, buffer, capacity):
        if base.value == missing_path:
            return 0
        name = (
            "C:\\"
            + ("nested\\" * 700 if long_name else "")
            + f"module-{base.value:X}.dll"
        )
        buffer.value = name[: capacity - 1]
        return min(capacity, len(name))

    def module_info(_handle, base, info, _size):
        info._obj.lpBaseOfDll = base.value
        info._obj.SizeOfImage = 0x1000
        return 1

    native = SimpleNamespace(
        EnumProcessModulesEx=NativeCall(enumerate_modules),
        EnumProcessModules=NativeCall(enumerate_modules),
        GetModuleFileNameExW=NativeCall(module_path),
        GetModuleInformation=NativeCall(module_info),
    )
    monkeypatch.setattr(live.ctypes, "WinDLL", lambda *_a, **_k: native)
    monkeypatch.setattr(live, "_process_identity", lambda _h: "C:\\war3.exe")
    monkeypatch.setattr(live, "_process_creation_time", lambda _h: 42)
    return native, calls


def test_module_growth_retries_until_actual_buffer_holds_every_module(monkeypatch):
    _api, calls = native_modules(monkeypatch, [1, 2, 5, 9, 9])
    modules = live.enum_modules(123)
    assert len(modules) == 9 and modules.complete and not modules.diagnostics
    assert len(calls) == 5
    assert modules[-1][1] == 0x108000


def test_module_failure_retains_last_confirmed_prefix_and_discloses_gap(monkeypatch):
    native_modules(monkeypatch, [1, 3], fail_after=2)
    modules = live.enum_modules(123)
    assert len(modules) == 1 and not modules.complete
    assert any("保留已确认前缀" in text for text in modules.diagnostics)


def test_module_unreadable_path_keeps_later_modules(monkeypatch):
    native_modules(monkeypatch, [3, 3], missing_path=0x101000)
    modules = live.enum_modules(123)
    assert [entry[1] for entry in modules] == [0x100000, 0x102000]
    assert not modules.complete and "101000" in modules.diagnostics[0]


def test_null_module_slot_remains_an_explicit_incomplete_observation(monkeypatch):
    native, _calls = native_modules(monkeypatch, [3, 3])
    original = native.EnumProcessModulesEx

    def with_unloaded_module(handle, array, capacity, needed, flags):
        result = original(handle, array, capacity, needed, flags)
        if array is not None:
            array[1] = 0
        return result

    native.EnumProcessModulesEx = NativeCall(with_unloaded_module)
    modules = live.enum_modules(123)
    assert [entry[1] for entry in modules] == [0x100000, 0x102000]
    assert not modules.complete and "第 2 项为空" in modules.diagnostics[0]


def test_module_paths_have_no_fixed_2048_character_window(monkeypatch):
    native_modules(monkeypatch, [1, 1], long_name=True)
    modules = live.enum_modules(123)
    assert modules.complete and len(modules[0][0]) > 4096


def test_module_unaligned_byte_count_cannot_overrun_or_allocate(monkeypatch):
    native, _calls = native_modules(monkeypatch, [])

    def invalid(_handle, _array, _size, needed, *_flags):
        needed._obj.value = 0xFFFFFFFF
        return 1

    native.EnumProcessModulesEx = NativeCall(invalid)
    modules = live.enum_modules(123)
    assert not modules and not modules.complete and "DWORD" in modules.diagnostics[0]


def test_module_enumeration_rechecks_process_identity(monkeypatch):
    native_modules(monkeypatch, [1, 1])
    times = iter([42, 43])
    monkeypatch.setattr(live, "_process_creation_time", lambda _h: next(times))
    modules = live.enum_modules(123)
    assert len(modules) == 1 and not modules.complete and modules.identity_changed


def image_process(
    monkeypatch, tmp_path, *, machine=0x14C, exe=False, versions=((1, 27, 0, 52240),)
):
    data, _loaded, fingerprint = pe_fixture(machine=machine, versions=versions)
    path = tmp_path / ("Warcraft III.exe" if exe else "Game.dll")
    path.write_bytes(data)
    monkeypatch.setattr(
        live, "enum_modules", lambda _h: [(str(path), 0x400000, fingerprint.image_size)]
    )
    header = pe.parse_pe_image(data).header
    assert header is not None
    monkeypatch.setattr(live, "read_loaded_pe_header", lambda *_a: header)
    return path, header


def test_classic_version_is_qualified_against_the_loaded_image(monkeypatch, tmp_path):
    _path, fingerprint = image_process(monkeypatch, tmp_path)
    info = live.detect_version(123)
    assert info["arch"] == "x86" and info["engine"] == "classic"
    assert info["version"] == "1.27.0.52240" and info["image_verified"]
    observed_fingerprint = info["image_fingerprint"]
    assert isinstance(observed_fingerprint, dict)
    assert observed_fingerprint["image_size"] == fingerprint.image_size
    assert info["known_offsets"] and "modules_seen" not in info


def test_reforged_exe_is_game_image_without_fabricating_game_dll(monkeypatch, tmp_path):
    image_process(
        monkeypatch, tmp_path, machine=0x8664, exe=True, versions=((3, 0, 0, 24268),)
    )
    info = live.detect_version(123)
    assert info["engine"] == "reforged" and info["arch"] == "x64"
    assert info["version"] == "3.0.0.24268" and info["image_verified"]
    assert info["game_dll"] is None
    image = info["game_image"]
    assert isinstance(image, dict)
    image_path = image["path"]
    assert isinstance(image_path, str) and image_path.endswith("Warcraft III.exe")


def test_disk_and_memory_metadata_mismatch_cannot_select_a_known_build(
    monkeypatch, tmp_path
):
    _path, fingerprint = image_process(monkeypatch, tmp_path)
    monkeypatch.setattr(
        live,
        "read_loaded_pe_header",
        lambda *_a: replace(fingerprint, timestamp=43),
    )
    info = live.detect_version(123)
    assert info["version"] is None and not info["image_verified"]
    assert info["arch"] == "x86" and "known_offsets" not in info
    diagnostics = info["diagnostics"]
    assert isinstance(diagnostics, list)
    assert any("不一致" in str(text) for text in diagnostics)


def test_same_fingerprint_with_a_different_resource_header_is_not_verified(
    monkeypatch, tmp_path
):
    _path, header = image_process(monkeypatch, tmp_path)
    monkeypatch.setattr(
        live,
        "read_loaded_pe_header",
        lambda *_a: replace(header, resource_rva=header.resource_rva + 16),
    )
    info = live.detect_version(123)
    assert not info["image_verified"] and info["version"] is None


def test_changed_loaded_header_cannot_supply_version_or_architecture(
    monkeypatch, tmp_path
):
    _path, fingerprint = image_process(monkeypatch, tmp_path)
    sequence = iter([fingerprint, replace(fingerprint, timestamp=43)])
    monkeypatch.setattr(live, "read_loaded_pe_header", lambda *_a: next(sequence))
    info = live.detect_version(123)
    assert info["version"] is None and info["arch"] == "unknown"
    assert not info["image_verified"]


def test_other_machine_is_explicitly_unknown_not_x86(monkeypatch, tmp_path):
    image_process(monkeypatch, tmp_path, machine=0xAA64)
    info = live.detect_version(123)
    assert info["arch"] == "unknown" and info["engine"] == "unknown"
    assert "known_offsets" not in info


def test_incomplete_module_prefix_retains_qualified_image_and_full_diagnostics(
    monkeypatch, tmp_path
):
    path, fingerprint = image_process(monkeypatch, tmp_path)
    modules = live.ModuleEnumeration()
    modules.append((str(path), 0x400000, fingerprint.image_size))
    modules.incomplete("tail module unavailable")
    monkeypatch.setattr(live, "enum_modules", lambda _h: modules)
    info = live.detect_version(123)
    assert info["image_verified"] and not info["modules_complete"]
    diagnostics = info["diagnostics"]
    assert isinstance(diagnostics, list)
    assert "tail module unavailable" in diagnostics
    modules.identity_changed = True
    changed = live.detect_version(123)
    assert changed["version"] is None and not changed["image_verified"]


@pytest.mark.parametrize("short", [False, True])
def test_loaded_header_reader_requires_exact_process_reads(monkeypatch, short):
    _disk, loaded, fingerprint = pe_fixture(pe_offset=0x11000)
    base = 0x140000000

    def read_memory(_handle, address, buffer, size, got):
        offset = address.value - base
        payload = loaded[offset : offset + size - (1 if short else 0)]
        ctypes.memmove(buffer, payload, len(payload))
        got._obj.value = len(payload)
        return 1

    monkeypatch.setattr(live, "k32", SimpleNamespace(ReadProcessMemory=read_memory))
    assert live.read_loaded_pe_fingerprint(123, base, len(loaded)) == (
        None if short else fingerprint
    )


def test_real_current_process_module_and_header_apis_need_no_game_or_elevation():
    live.mem_setup()
    handle = live.k32.GetCurrentProcess()
    modules = live.enum_modules(handle)
    assert modules.complete, modules.diagnostics
    process_path = live._process_identity(handle)
    assert process_path is not None
    executable = [
        module for module in modules if module[0].casefold() == process_path.casefold()
    ]
    assert len(executable) == 1
    path, base, size = executable[0]
    assert live.read_loaded_pe_fingerprint(
        handle, base, size
    ) == live.read_pe_fingerprint(path)


def test_scan_limits_use_native_range_and_never_assume_unknown_means_x86(monkeypatch):
    def native_info(info):
        info._obj.maximum_address = 0x7FFFFFFEFFFF

    monkeypatch.setattr(
        live, "k32", SimpleNamespace(GetNativeSystemInfo=NativeCall(native_info))
    )
    assert live.process_scan_limit({"arch": "x86"}) == 1 << 32
    assert live.process_scan_limit({"arch": "unknown"}) == 0x7FFFFFFF0000
    assert live.process_scan_limit({"arch": "x64"}) == 0x7FFFFFFF0000


@pytest.mark.parametrize("arch", ["x64", "unknown"])
def test_live_uses_full_scan_and_reports_image_diagnostics_without_x86_fallback(
    monkeypatch, arch
):
    from gametool import hero_chain

    snapshots = []
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(live, "_process_identity", lambda _h: "Warcraft III.exe")
    monkeypatch.setattr(live, "_process_creation_time", lambda _h: 42)
    monkeypatch.setattr(live, "_integrity_rid", lambda _h: None)
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=lambda _h: None))
    monkeypatch.setattr(live, "_read_icon_slots", lambda *_a: [])
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _h: {
            "arch": arch,
            "engine": "reforged" if arch == "x64" else "unknown",
            "version": None,
            "game_dll": None,
            "game_image": {"base": 0x140000000},
            "diagnostics": ["image evidence diagnostic"],
        },
    )

    def snapshot(_handle, limit):
        snapshots.append(limit)
        return [], 0

    def rejected(*_a, **_k):
        raise AssertionError("x64/unknown architecture cannot use an x86 chain")

    monkeypatch.setattr(live, "snapshot", snapshot)
    monkeypatch.setattr(hero_chain, "read_inventory", rejected)
    result = live.read_live("unused", verbose=False)
    assert snapshots == [1 << (ctypes.sizeof(ctypes.c_void_p) * 8)]
    assert "image evidence diagnostic" in result["notes"]
    assert any("结构链需要" in text for text in result["notes"])


def test_object_dump_consumes_image_architecture_and_complete_diagnostics(
    monkeypatch, tmp_path
):
    from gametool import live_object_dump as dump

    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _h: {
            "arch": "x64",
            "version": "3.0.0.24268",
            "diagnostics": ["module gap A", "module gap B"],
        },
    )
    monkeypatch.setattr(live, "process_scan_limit", lambda _version: 1 << 47)
    monkeypatch.setattr(
        dump.ctypes,
        "WinDLL",
        lambda *_a, **_k: SimpleNamespace(CloseHandle=lambda _h: None),
    )
    limits = []

    def snapshot(_handle, limit):
        limits.append(limit)
        return [], 0, 0

    monkeypatch.setattr(dump, "_snapshot_regions", snapshot)
    result = dump.dump_live_objects(str(tmp_path / "output"), verbose=False)
    assert limits == [1 << 47]
    assert "module gap A" in result.notes and "module gap B" in result.notes
