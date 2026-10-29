"""Offline handle identity and profile evidence must survive missing bytes honestly."""

from __future__ import annotations

import struct
from dataclasses import replace

import pytest

from gametool import live_handle_chain as hc


BASE = 0x70000000
MANAGER = 0x10000000
TABLE_A = 0x11000000
TABLE_B = 0x12000000
WRAPPER = 0x13000000
OBJECT = 0x14000000
OFFSETS = hc.HANDLE_CHAIN_OFFSETS["1.27.0.52240"]


def _memory(count: int = 2) -> dict[int, bytes]:
    manager = bytearray(0x40)
    for base_off, bound_off, address, bound in (
        (OFFSETS.hm_tableA_base_off, OFFSETS.hm_tableA_bound_off, TABLE_A, count + 1),
        (OFFSETS.hm_tableB_base_off, OFFSETS.hm_tableB_bound_off, TABLE_B, 1),
    ):
        struct.pack_into("<I", manager, base_off, address)
        struct.pack_into("<I", manager, bound_off, bound)
    data = {
        BASE + OFFSETS.handle_mgr_global_rva: struct.pack("<I", MANAGER),
        MANAGER: bytes(manager),
        TABLE_B: bytes(8),
    }
    entries = bytearray((count + 1) * 8)
    for ordinal in range(count):
        index = ordinal + 1
        wrapper = WRAPPER + ordinal * 0x100
        obj = OBJECT + ordinal * 0x400
        generation = 0x5000 + ordinal
        struct.pack_into("<II", entries, index * 8, 0xFFFFFFFE, wrapper)
        body = bytearray(0x60)
        struct.pack_into("<I", body, OFFSETS.wrapper_gen_off, generation)
        struct.pack_into("<I", body, OFFSETS.wrapper_obj_off, obj)
        data[wrapper] = bytes(body)
        unit = bytearray(0x200)
        struct.pack_into("<II", unit, OFFSETS.entry_pair_off, index, generation)
        struct.pack_into(
            "<I", unit, OFFSETS.unit_type_off, int.from_bytes(b"h001", "big")
        )
        data[obj] = bytes(unit)
    data[TABLE_A] = bytes(entries)
    return data


class IncompleteReader(hc.MemoryReader):
    def __init__(self, data: dict[int, bytes], failures: dict[int, bytes | None]):
        super().__init__(data.items())
        self.failures = failures

    def read(self, addr: int, size: int) -> bytes | None:
        if addr in self.failures:
            return self.failures[addr]
        return super().read(addr, size)


def _set_u32(data: dict[int, bytes], base: int, offset: int, value: int) -> None:
    changed = bytearray(data[base])
    struct.pack_into("<I", changed, offset, value)
    data[base] = bytes(changed)


@pytest.mark.parametrize("bad", [None, b"", b"\0", b"\0\0\0"])
@pytest.mark.parametrize(
    ("address", "role"),
    [
        (TABLE_A + 8, "表项"),
        (WRAPPER + OFFSETS.wrapper_gen_off, "generation"),
        (WRAPPER + OFFSETS.wrapper_alive_off, "alive"),
        (WRAPPER + OFFSETS.wrapper_obj_off, "object"),
        (OBJECT + OFFSETS.entry_pair_off, "自身句柄对"),
    ],
)
def test_incomplete_identity_never_becomes_a_live_object(address, role, bad):
    reader = IncompleteReader(_memory(), {address: bad})
    system = hc.HandleSystem(reader, BASE, OFFSETS)
    assert system.live_objects() == [OBJECT + 0x400]
    assert not system.live_complete
    assert len(system.live_diagnostics) == 1
    assert role in system.live_diagnostics[0]
    assert f"0x{address:X}" in system.live_diagnostics[0]
    if bad is not None:
        assert "短读" in system.live_diagnostics[0]


@pytest.mark.parametrize("bad", [None, b"", b"\0\0\0"])
@pytest.mark.parametrize(
    "address",
    [
        BASE + OFFSETS.handle_mgr_global_rva,
        MANAGER + OFFSETS.hm_tableA_base_off,
        MANAGER + OFFSETS.hm_tableA_bound_off,
    ],
)
def test_incomplete_manager_is_diagnostic_without_unpack_errors(address, bad):
    system = hc.HandleSystem(IncompleteReader(_memory(), {address: bad}), BASE, OFFSETS)
    assert not system.valid
    assert system.live_objects() == []
    assert not system.live_complete
    assert any(f"0x{address:X}" in issue for issue in system.live_diagnostics)


@pytest.mark.parametrize(
    ("base", "offset", "value", "reason"),
    [
        (TABLE_A, 8, 0, "未标记活动"),
        (TABLE_A, 8, 0xFFFFFFFF, "未标记活动"),
        (WRAPPER, OFFSETS.wrapper_alive_off, 1, "已失效"),
        (WRAPPER, OFFSETS.wrapper_gen_off, 0x9999, "世代不符"),
        (OBJECT, OFFSETS.entry_pair_off, 2, "回链不符"),
        (OBJECT, OFFSETS.entry_pair_off, 0x80000001, "回链不符"),
        (OBJECT, OFFSETS.entry_pair_off + 4, 0x9999, "世代不符"),
        (WRAPPER, OFFSETS.wrapper_obj_off, OBJECT + 0x400, "回链不符"),
    ],
)
def test_stale_or_conflicting_handle_never_reuses_plausible_object_fields(
    base, offset, value, reason
):
    data = _memory()
    _set_u32(data, base, offset, value)
    system = hc.HandleSystem(hc.MemoryReader(data.items()), BASE, OFFSETS)
    assert system.live_objects() == [OBJECT + 0x400]
    assert not system.live_complete
    assert reason in " ".join(system.live_diagnostics)


def test_readable_zero_alive_flag_and_both_table_identities_are_confirmed():
    data = _memory()
    _set_u32(data, TABLE_A, 8, 0)
    _set_u32(data, TABLE_A, 12, 0)
    data[TABLE_B] = struct.pack("<II", 0xFFFFFFFE, WRAPPER)
    _set_u32(data, OBJECT, OFFSETS.entry_pair_off, 0x80000000)
    system = hc.HandleSystem(hc.MemoryReader(data.items()), BASE, OFFSETS)
    assert system.live_objects() == [OBJECT + 0x400, OBJECT]
    assert system.live_complete and not system.live_diagnostics


def test_every_declared_entry_and_every_failure_is_retained():
    count = 300
    data = _memory(count)
    failures: dict[int, bytes | None] = {
        WRAPPER + ordinal * 0x100 + OFFSETS.wrapper_alive_off: None
        for ordinal in range(count - 1)
    }
    system = hc.HandleSystem(IncompleteReader(data, failures), BASE, OFFSETS)
    assert system.live_objects() == [OBJECT + (count - 1) * 0x400]
    assert len(system.live_diagnostics) == count - 1
    assert "索引 1 " in system.live_diagnostics[0]
    assert f"索引 {count - 1} " in system.live_diagnostics[-1]
    assert not system.live_complete


def test_unreadable_tail_uses_encoded_bound_without_claiming_complete_count():
    data = _memory()
    _set_u32(data, MANAGER, OFFSETS.hm_tableA_bound_off, 9)
    system = hc.HandleSystem(hc.MemoryReader(data.items()), BASE, OFFSETS)
    assert system.live_objects() == [OBJECT, OBJECT + 0x400]
    assert len(system.live_diagnostics) == 6
    assert "索引 8 " in system.live_diagnostics[-1]
    assert not system.live_complete


@pytest.mark.parametrize("bad", [None, b"", b"\0", b"\0\0\0"])
def test_direct_resolution_also_rejects_short_validation_bytes(bad):
    reader = IncompleteReader(_memory(), {WRAPPER + OFFSETS.wrapper_alive_off: bad})
    system = hc.HandleSystem(reader, BASE, OFFSETS)
    obj, evidence, diagnostics = system.resolve_evidence(1, 0x5000)
    assert obj is None
    assert evidence["entry_flag"] == 0xFFFFFFFE
    assert evidence["generation"] == 0x5000
    assert "alive 不可读" in " ".join(diagnostics)


def test_direct_resolution_requires_an_active_entry():
    data = _memory()
    _set_u32(data, TABLE_A, 8, 0xFFFFFFFF)
    system = hc.HandleSystem(hc.MemoryReader(data.items()), BASE, OFFSETS)
    obj, evidence, diagnostics = system.resolve_evidence(1, 0x5000)
    assert obj is None and evidence["entry_flag"] == 0xFFFFFFFF
    assert "未标记活动" in " ".join(diagnostics)


@pytest.mark.parametrize("bad", [None, b"", b"\0", b"\0\0\0"])
def test_matching_pe_metadata_cannot_turn_missing_checks_into_runtime_patches(bad):
    fingerprint = hc.ProfileFingerprint(0x14C, 7, 0x1000)
    profile = replace(
        hc.resolve_profile("1.27.0.52240"),
        fingerprint=fingerprint,
        checks=(
            hc.ProfileCheck(0x10, b"\0" * 4, "missing"),
            hc.ProfileCheck(0x20, b"\0" * 4, "changed"),
            hc.ProfileCheck(0x30, b"\0" * 4, "matching"),
        ),
    )
    reader = IncompleteReader(
        {BASE: bytes(64)}, {BASE + 0x10: bad, BASE + 0x20: b"\x90" * 4}
    )
    ok, failures, patches = hc.verify_profile(reader, BASE, profile, fingerprint)
    assert not ok and len(failures) == 1 and len(patches) == 1
    assert "missing@0x10" in failures[0]
    assert "changed@0x20" in patches[0] and "90909090" in patches[0]
    assert not any("missing" in patch for patch in patches)


def test_all_unreadable_profile_check_locations_are_retained():
    original = hc.resolve_profile("1.27.0.52240")
    profile = replace(
        original,
        checks=tuple(hc.ProfileCheck(index * 8, bytes(4)) for index in range(300)),
    )
    ok, failures, patches = hc.verify_profile(
        hc.MemoryReader([]), BASE, profile, profile.fingerprint
    )
    assert not ok and len(failures) == 300 and not patches
    assert "@0x958" in failures[-1]


@pytest.mark.parametrize("engine", ["classic", "reforged"])
def test_known_classic_version_never_selects_an_x86_chain_for_an_x64_image(engine):
    profile = hc.resolve_profile("1.27.0.52240", engine, "x64")
    assert profile.tier == "reforged-pending"
    assert profile.arch == "x64"
    assert profile.handle_chain is None
