"""Synthetic regression and reproducible dense-resource calibration benchmark."""

from __future__ import annotations

import json
import math
import random
import struct
from dataclasses import asdict

import pytest

from gametool import live_handle_chain as hc


@pytest.fixture(autouse=True)
def isolated_resource_cache(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(hc, "_resource_anchors", None)
    monkeypatch.setattr(hc, "_resource_cache_hit", False)


def _reference_layout(
    reader: hc.MemoryReader,
    gold: float,
    lumber: float,
    window: int,
    *,
    legacy: bool = False,
) -> list[hc.PlayerResources]:
    """Independent Cartesian oracle; legacy=True reproduces the old algorithm."""
    gold_addresses: list[int] = []
    lumber_addresses: list[int] = []
    for base, data in reader.iter_regions():
        if legacy and len(data) < 0x100:
            continue
        stop = len(data) - 4 if legacy else len(data) - 3
        for offset in range(0, stop, 4):
            value = struct.unpack_from("<f", data, offset)[0]
            if not math.isfinite(value) or not 0 <= value < 10_000_000:
                continue
            is_gold = abs(value - gold) <= 1.0
            if is_gold:
                gold_addresses.append(base + offset)
            if (not legacy or not is_gold) and abs(value - lumber) <= 1.0:
                lumber_addresses.append(base + offset)
    pairs = [
        (gold_address, lumber_address - gold_address)
        for gold_address in gold_addresses
        for lumber_address in lumber_addresses
        if 0 < abs(lumber_address - gold_address) <= window
        and (lumber_address - gold_address) % 4 == 0
    ]
    counts: dict[int, int] = {}
    for _, delta in pairs:
        counts[delta] = counts.get(delta, 0) + 1
    if not counts:
        return []
    best = max(counts, key=lambda delta: counts[delta])
    rows: list[hc.PlayerResources] = []
    for address in sorted(address for address, delta in pairs if delta == best):
        gr, lr = reader.read(address, 4), reader.read(address + best, 4)
        if gr and lr:
            rows.append(
                hc.PlayerResources(
                    address,
                    struct.unpack("<f", gr)[0],
                    struct.unpack("<f", lr)[0],
                    hc._probe_food(reader, address, best),
                )
            )
    return rows


def _reader(values: list[float], base: int = 0x20000000) -> hc.MemoryReader:
    return hc.MemoryReader([(base, struct.pack("<" + "f" * len(values), *values))])


@pytest.mark.parametrize("window", [0, 3, 4, 7, 32, 256, 1024])
@pytest.mark.parametrize("reported", [(100.0, 1.0), (100.0, 100.0), (100.0, 101.0)])
def test_window_join_matches_complete_cartesian_oracle(
    window: int, reported: tuple[float, float]
) -> None:
    generator = random.Random(0x2599)
    choices = [0.0, 1.0, 2.0, 99.0, 100.0, 100.5, 101.0, 102.0, math.nan, math.inf]
    regions = []
    for base, count in ((0x10001, 45), (0x10101, 7), (0x10202, 67)):
        values = [generator.choice(choices) for _ in range(count)]
        regions.append((base, struct.pack("<" + "f" * count, *values) + b"\x00"))
    reader = hc.MemoryReader(regions)
    assert hc.find_resource_layout(reader, *reported, window, use_cache=False) == (
        _reference_layout(reader, *reported, window)
    )


@pytest.mark.parametrize("gold, lumber", [(100.0, 100.0), (100.0, 101.0)])
def test_equal_or_overlapping_values_keep_both_resource_roles(
    gold: float, lumber: float
) -> None:
    reader = _reader([100.0, 100.5, 101.0, 999.0])
    expected = _reference_layout(reader, gold, lumber, 8)
    assert expected
    assert hc.find_resource_layout(reader, gold, lumber, 8, use_cache=False) == expected


def test_complete_float_coverage_includes_short_regions_and_last_slots() -> None:
    reader = _reader([2599.0, 1.0])
    assert list(hc._iter_float_slots(reader)) == [
        (0x20000000, 2599.0),
        (0x20000004, 1.0),
    ]
    rows = hc.find_resource_layout(reader, 2599.0, 1.0, use_cache=False)
    assert len(rows) == 1 and rows[0].addr == 0x20000000


def test_windows_keep_captured_region_gaps_alignment_and_partial_tails() -> None:
    reader = hc.MemoryReader(
        [
            (0x20001, struct.pack("<f", 2599.0) + b"\xff"),
            (0x20009, struct.pack("<f", 1.0)),
            (0x20012, struct.pack("<f", 1.0)),
            (0x20021, struct.pack("<f", 1.0)[:3]),
        ]
    )
    assert hc.find_resource_layout(reader, 2599.0, 1.0, 32, use_cache=False) == (
        _reference_layout(reader, 2599.0, 1.0, 32)
    )
    assert hc._resource_anchors == [(0x20001, 8)]


def test_physically_adjacent_fragments_keep_the_readers_complete_float() -> None:
    payload = struct.pack("<ff", 2599.0, 1.0)
    reader = hc.MemoryReader([(0x20000, payload[:3]), (0x20003, payload[3:])])
    assert hc.find_resource_layout(reader, 2599.0, 1.0, 4, use_cache=False) == (
        _reference_layout(reader, 2599.0, 1.0, 4)
    )


def test_overlapping_regions_preserve_pair_multiplicity_and_tie_order() -> None:
    first = struct.pack("<ffff", 2599.0, 1.0, 2599.0, 1.0)
    second = struct.pack("<ff", 1.0, 2599.0)
    reader = hc.MemoryReader([(0x20000, first), (0x20004, second)])
    expected = _reference_layout(reader, 2599.0, 1.0, 8)
    assert hc.find_resource_layout(reader, 2599.0, 1.0, 8, use_cache=False) == expected


def _dense_reader(size: int, gold_count: int) -> hc.MemoryReader:
    slots = size // 4
    if gold_count < 1 or slots <= gold_count:
        raise ValueError("synthetic input needs one distinct slot per gold anchor")
    blob = bytearray(size)
    for index in range(gold_count):
        offset = ((index + 1) * slots // (gold_count + 1)) * 4
        struct.pack_into("<f", blob, offset, 2599.0)
    return hc.MemoryReader([(0x20000000, bytes(blob))])


def test_dense_zero_lumber_preserves_every_anchor_and_legacy_results() -> None:
    reader = _dense_reader(128 * 1024, 64)
    expected = _reference_layout(reader, 2599.0, 1.0, 256, legacy=True)
    found = hc.find_resource_layout(reader, 2599.0, 1.0, 256, use_cache=False)
    assert len(found) == 64 and found == expected


def test_anchor_cache_revalidates_values_and_rescans_after_any_failure() -> None:
    first = _reader([2599.0, 1.0, 2599.5, 1.5])
    rows = hc.find_resource_layout(first, 2599.0, 1.0)
    assert len(rows) == 2 and not hc.cached_resource_hit()
    assert hc.find_resource_layout(first, 2599.0, 1.0) == rows
    assert hc.cached_resource_hit()
    moved = _reader([2599.0, 1.0], base=0x30000000)
    fresh = hc.find_resource_layout(moved, 2599.0, 1.0)
    assert len(fresh) == 1 and fresh[0].addr == 0x30000000
    assert not hc.cached_resource_hit()


def _peak_resident_bytes() -> int | None:
    import os

    if os.name != "nt":
        return None
    import ctypes
    from ctypes import wintypes

    class Counters(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("PageFaultCount", wintypes.DWORD),
            ("PeakWorkingSetSize", ctypes.c_size_t),
            ("WorkingSetSize", ctypes.c_size_t),
            ("QuotaPeakPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPagedPoolUsage", ctypes.c_size_t),
            ("QuotaPeakNonPagedPoolUsage", ctypes.c_size_t),
            ("QuotaNonPagedPoolUsage", ctypes.c_size_t),
            ("PagefileUsage", ctypes.c_size_t),
            ("PeakPagefileUsage", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.GetCurrentProcess.restype = wintypes.HANDLE
    psapi = ctypes.WinDLL("psapi", use_last_error=True)
    query = psapi.GetProcessMemoryInfo
    query.argtypes = [wintypes.HANDLE, ctypes.POINTER(Counters), wintypes.DWORD]
    query.restype = wintypes.BOOL
    counters = Counters()
    counters.cb = ctypes.sizeof(counters)
    if not query(kernel.GetCurrentProcess(), ctypes.byref(counters), counters.cb):
        raise ctypes.WinError(ctypes.get_last_error())
    return counters.PeakWorkingSetSize


def _benchmark_worker(algorithm: str, size: int, gold_count: int) -> None:
    import hashlib
    import time
    import tracemalloc

    import numpy  # Warm the same numerical runtime before either measurement.

    assert numpy is not None
    reader = _dense_reader(size, gold_count)
    tracemalloc.start()
    started = time.perf_counter()
    rows = (
        _reference_layout(reader, 2599.0, 1.0, 256, legacy=True)
        if algorithm == "legacy"
        else hc.find_resource_layout(reader, 2599.0, 1.0, 256, use_cache=False)
    )
    elapsed = time.perf_counter() - started
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    payload = json.dumps([asdict(row) for row in rows], sort_keys=True).encode()
    print(
        json.dumps(
            {
                "algorithm": algorithm,
                "input_bytes": size,
                "anchors": len(rows),
                "elapsed_s": elapsed,
                "peak_traced_bytes": peak,
                "peak_resident_bytes": _peak_resident_bytes(),
                "rows_sha256": hashlib.sha256(payload).hexdigest(),
            },
            sort_keys=True,
        ),
        flush=True,
    )


def _benchmark_main() -> None:
    import argparse
    import subprocess
    import sys

    from gametool.dev_test import create_test_environment

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--measure", choices=("legacy", "window"))
    parser.add_argument("--bytes", type=int, default=2 * 1024 * 1024)
    parser.add_argument("--gold-count", type=int, default=16)
    args = parser.parse_args()
    if args.measure:
        _benchmark_worker(args.measure, args.bytes, args.gold_count)
        return
    for algorithm in ("legacy", "window"):
        subprocess.run(
            [
                sys.executable,
                "-X",
                "utf8",
                __file__,
                "--measure",
                algorithm,
                "--bytes",
                str(args.bytes),
                "--gold-count",
                str(args.gold_count),
            ],
            env=create_test_environment(),
            check=True,
        )


if __name__ == "__main__":
    _benchmark_main()
