"""Unified game-data inventory capability across readable backends."""

from __future__ import annotations

import hashlib
from pathlib import Path

from w3xtool.casc_browser import CascBrowserModel
from w3xtool.casc_source import CascDataSource
from w3xtool.casclib_enumeration import CascNameType
from w3xtool.game_data_source import DirectoryDataSource


def _idx_row(encoding_key: bytes, offset: int, size: int) -> bytes:
    return encoding_key[:9] + b"\x00" + offset.to_bytes(4, "big") + size.to_bytes(4, "little")


def _path_map_source(root: Path, paths: tuple[str, ...]) -> CascDataSource:
    data_dir = root / "Data" / "data"
    data_dir.mkdir(parents=True)
    (root / ".build.info").write_text("Build Key|Version\n", encoding="utf-8")
    payload = b"BLTE\x00\x00\x00\x00Ndata"
    block = hashlib.md5(payload).digest() + (len(payload) + 30).to_bytes(4, "little")
    block += b"\x00" * 10 + payload
    offset = 32
    (data_dir / "data.000").write_bytes(b"\x00" * offset + block)
    key = bytes.fromhex("00112233445566778899aabbccddeeff")
    (data_dir / "0000000000000000.idx").write_bytes(_idx_row(key, offset, len(payload)))
    lines = "".join(f"{path}\t{key.hex()}\n" for path in paths)
    (root / "w3xray-casc-paths.tsv").write_text(lines, encoding="utf-8")
    return CascDataSource(str(root))


def test_directory_source_exposes_sorted_known_path_inventory(tmp_path: Path) -> None:
    # Given: extracted client files have mixed path spelling and unrelated data.
    (tmp_path / "Units").mkdir()
    (tmp_path / "Units" / "HumanUnitStrings.txt").write_bytes(b"unit strings")
    (tmp_path / "Units" / "AbilityData.slk").write_bytes(b"ability")
    source = DirectoryDataSource(str(tmp_path))

    # When: its known-path inventory is filtered with a case-insensitive mask.
    entries = tuple(source.iter_entries("*unitstrings.TXT"))

    # Then: real spelling is retained and no native identity is fabricated.
    assert [entry.name for entry in entries] == ["Units\\HumanUnitStrings.txt"]
    assert all(entry.name_type is CascNameType.FULL for entry in entries)
    assert all(entry.file_data_id is None and not entry.ckey and not entry.ekey for entry in entries)


def test_path_map_source_exposes_deterministic_known_path_inventory(tmp_path: Path) -> None:
    # Given: a path map is intentionally not ordered by logical path.
    source = _path_map_source(
        tmp_path,
        ("UI\\Zeta.txt", "Units\\Human Unit Strings.txt", "UI\\Alpha.txt"),
    )

    # When: all known entries are enumerated.
    entries = tuple(source.iter_entries("*"))

    # Then: names are sorted, stable and explicitly path-based.
    assert [entry.name for entry in entries] == [
        "UI\\Alpha.txt",
        "UI\\Zeta.txt",
        "Units\\Human Unit Strings.txt",
    ]
    assert all(entry.name_type is CascNameType.FULL for entry in entries)


def test_supports_inventory_and_browser_accept_fallback_sources(tmp_path: Path) -> None:
    # Given: one readable directory source and an unrelated read-only object.
    from w3xtool.game_data_inventory import (
        GameDataInventoryView,
        supports_inventory,
    )

    (tmp_path / "UI").mkdir()
    (tmp_path / "UI" / "Test.txt").write_bytes(b"test")
    source = DirectoryDataSource(str(tmp_path))

    # When: capability and paged browser paths inspect the fallback source.
    model = CascBrowserModel(source, page_size=10)
    model.reset(mask="*.txt", listfile="ignored-native-listfile.txt")
    page = model.next_page()

    # Then: inventory is supported as known paths without a native-only call shape.
    assert supports_inventory(source)
    assert not supports_inventory(None)
    assert source.inventory_view is GameDataInventoryView.KNOWN_PATHS
    assert [entry.name for entry in page.entries] == ["UI\\Test.txt"]
