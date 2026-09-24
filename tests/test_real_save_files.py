"""Read-only real save file evidence analysis."""

from __future__ import annotations

import hashlib
import importlib
import os
from pathlib import Path
import struct
import subprocess
import sys
import zlib

import pytest

from w3xtool.api import GameObject, MapData


def _map_with_save_contract() -> MapData:
    hero = GameObject(
        category="单位",
        ext="w3u",
        obj_id="H001",
        base_id="H001",
        name="测试英雄",
        is_custom=True,
    )
    return MapData(
        path="map.w3x",
        name="测试地图",
        objects={"单位": [hero]},
        scripts={
            "war3map.j": (
                'call DzAPI_Map_SaveServerValue(Player(0), "hero.level", "7")\n'
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)\n"
            ),
        },
        obj_index={"H001": hero},
    )


def test_preload_save_matches_script_key_and_map_object_without_modifying_file(
    tmp_path: Path,
) -> None:
    # Given: a local Preload-style save containing one known key and object rawcode.
    save = tmp_path / "save" / "profile.pld"
    save.parent.mkdir()
    save.write_text(
        "function PreloadFiles takes nothing returns nothing\n"
        '    call Preload("hero.level=7;unit=H001")\n'
        "endfunction\n",
        encoding="utf-8",
    )
    before = hashlib.sha256(save.read_bytes()).hexdigest()
    save_module = importlib.import_module("w3xtool.real_save_files")

    # When: the real save directory is analyzed against the loaded map.
    report = save_module.analyze_real_save_path(save.parent, _map_with_save_contract())

    # Then: evidence is cross-referenced and the source remains byte-for-byte unchanged.
    assert len(report.files) == 1
    record = report.files[0]
    assert record.kind.value == "preload"
    assert record.matched_keys == ("hero.level",)
    assert record.object_matches[0].code == "H001"
    assert record.object_matches[0].name == "测试英雄"
    assert hashlib.sha256(save.read_bytes()).hexdigest() == before


def test_binary_save_is_inventoried_without_false_text_evidence(tmp_path: Path) -> None:
    # Given: an opaque binary platform save with no readable payload.
    save = tmp_path / "opaque.sav"
    save.write_bytes(bytes(range(256)) * 4)
    save_module = importlib.import_module("w3xtool.real_save_files")

    # When: it crosses the bounded read-only analyzer.
    report = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: metadata is preserved but no decryption or invented key match occurs.
    assert report.files[0].kind.value == "binary"
    assert report.files[0].matched_keys == ()
    assert report.files[0].object_matches == ()
    assert "未解密" in report.files[0].diagnostic


def _build_w3z_container(raw: bytes) -> bytes:
    signature = b"Warcraft III recorded game\x1a\x00"
    compressor = zlib.compressobj(level=1, wbits=15)
    compressed = compressor.compress(raw) + compressor.flush(zlib.Z_SYNC_FLUSH)
    header_crc = (
        zlib.crc32(struct.pack("<III", len(compressed), len(raw), 0)) & 0xFFFFFFFF
    )
    data_crc = zlib.crc32(compressed) & 0xFFFFFFFF
    checksum = (((data_crc >> 16) ^ (data_crc & 0xFFFF)) & 0xFFFF) << 16 | (
        (header_crc >> 16) ^ (header_crc & 0xFFFF)
    ) & 0xFFFF
    header = signature + struct.pack(
        "<5I", 48, 48 + 12 + len(compressed), 0, len(raw), 1
    )
    return (
        header + struct.pack("<III", len(compressed), len(raw), checksum) + compressed
    )


def test_w3z_save_container_yields_decoded_binary_evidence(tmp_path: Path) -> None:
    # Given: a recorded-save container holding binary state with one key, code, and string.
    save = tmp_path / "profile.w3z"
    raw = (
        b"\x00\x01\x02hero.level\x00H001\x00"
        b'"gold:900"\x00' + '"equipped:续命剑"'.encode("utf-8") + b"\x00\x03"
    )
    save.write_bytes(_build_w3z_container(raw))
    before = hashlib.sha256(save.read_bytes()).hexdigest()
    save_module = importlib.import_module("w3xtool.real_save_files")

    # When: the container crosses the bounded read-only analyzer.
    report = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: decoded evidence is cross-referenced and the source stays unchanged.
    record = report.files[0]
    assert record.kind.value == "w3z"
    assert record.matched_keys == ("hero.level",)
    assert record.object_matches[0].code == "H001"
    assert record.object_matches[0].name == "测试英雄"
    assert "gold:900" in record.printable_strings
    assert "equipped:续命剑" in record.printable_strings
    assert "块共" in record.diagnostic
    assert hashlib.sha256(save.read_bytes()).hexdigest() == before
    text = save_module.format_real_save_report_tsv(report)
    assert "profile.w3z\tw3z" in text
    assert "H001:测试英雄" in text


def test_w3z_corrupt_container_reports_failure_without_evidence(tmp_path: Path) -> None:
    # Given: a recorded-save container whose compressed payload was damaged.
    save = tmp_path / "broken.w3z"
    container = bytearray(_build_w3z_container(b"state\x00payload"))
    container[-1] ^= 0xFF
    save.write_bytes(bytes(container))
    save_module = importlib.import_module("w3xtool.real_save_files")

    # When: the analyzer meets the corrupt container.
    report = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: only metadata survives and the failure reason is explicit.
    record = report.files[0]
    assert record.kind.value == "w3z"
    assert record.matched_keys == ()
    assert record.object_matches == ()
    assert record.printable_strings == ()
    assert "w3z 容器校验失败" in record.diagnostic


def test_save_report_tsv_keeps_file_key_and_object_evidence(tmp_path: Path) -> None:
    # Given: one JSON save carrying the same key and object ID used by the map.
    save = tmp_path / "profile.json"
    save.write_text('{"hero.level": 7, "unit": "H001"}', encoding="utf-8")
    save_module = importlib.import_module("w3xtool.real_save_files")
    report = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # When: the report is rendered for export.
    text = save_module.format_real_save_report_tsv(report)

    # Then: the observable evidence is available without exposing invented plaintext.
    assert "profile.json\tjson" in text
    assert "hero.level" in text
    assert "H001:测试英雄" in text


def test_main_save_command_writes_read_only_report(tmp_path: Path) -> None:
    # Given: a real map fixture and a local JSON save file.
    root = Path(__file__).resolve().parents[1]
    map_path = root / "tests" / "fixtures" / "maps" / "war3net-map-script-builder.w3x"
    save = tmp_path / "profile.json"
    save.write_text('{"hero.level": 7}', encoding="utf-8")
    output = tmp_path / "save-report.tsv"

    # When: the public source/EXE command analyzes the save.
    result = subprocess.run(
        (
            sys.executable,
            str(root / "main.py"),
            "save",
            "--map",
            str(map_path),
            "--save",
            str(save),
            "--output",
            str(output),
        ),
        capture_output=True,
        encoding="utf-8",
        env={**os.environ, "PYTHONIOENCODING": "cp1252"},
        check=False,
        timeout=10,
    )

    # Then: it exits without opening GUI and produces the bounded evidence report.
    assert result.returncode == 0, result.stderr
    assert "profile.json\tjson" in output.read_text(encoding="utf-8")


def test_save_file_swap_after_metadata_check_does_not_read_symlink_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: a regular save is swapped for a symlink after its second stat call.
    save_dir = tmp_path / "saves"
    save_dir.mkdir()
    save = save_dir / "profile.txt"
    save.write_text('"safe-value"', encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text('"outside-secret" hero.level H001', encoding="utf-8")
    original_read_bytes = Path.read_bytes
    swapped = False

    def racing_read_bytes(path: Path) -> bytes:
        nonlocal swapped
        if path == save and not swapped:
            save.unlink()
            save.symlink_to(outside)
            swapped = True
        return original_read_bytes(path)

    monkeypatch.setattr(Path, "read_bytes", racing_read_bytes)
    save_module = importlib.import_module("w3xtool.real_save_files")

    # When: the directory is analyzed across the metadata/read boundary.
    report = save_module.analyze_real_save_path(save_dir, _map_with_save_contract())

    # Then: bytes outside the selected directory are never accepted as save evidence.
    assert report.files[0].matched_keys == ()
    assert report.files[0].object_matches == ()
    assert "outside-secret" not in report.files[0].printable_strings


def test_mpq_member_declared_oversize_is_rejected_before_decompression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: an MPQ-like save whose named member declares an oversized output.
    save = tmp_path / "profile.sav"
    save.write_bytes(b"MPQ\x1a" + b"\0" * 64)
    save_module = importlib.import_module("w3xtool.real_save_files")
    read_calls = 0

    class OversizedBlock:
        file_size = save_module.MAX_SAVE_FILE_SIZE + 1

    class FakeArchive:
        block_table = (OversizedBlock(),)

        def __init__(self, _path: str) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def list_files(self) -> list[str]:
            return ["huge.txt"]

        def block_index_of(self, _name: str) -> int:
            return 0

        def read_file(self, _name: str) -> bytes:
            nonlocal read_calls
            read_calls += 1
            return b"must not be allocated"

    monkeypatch.setattr(save_module, "MPQArchive", FakeArchive)

    # When: the save analyzer inspects named MPQ text.
    report = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: declared expansion is checked before read_file can allocate it.
    assert read_calls == 0
    assert report.files[0].kind.value == "mpq"


def test_mpq_named_text_respects_one_aggregate_decoded_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: several individually valid members exceed the aggregate text budget.
    save = tmp_path / "profile.sav"
    save.write_bytes(b"MPQ\x1a" + b"\0" * 64)
    save_module = importlib.import_module("w3xtool.real_save_files")
    member_size = 3 * 1024 * 1024
    read_calls = 0

    class Block:
        file_size = member_size

    class FakeArchive:
        block_table = tuple(Block() for _index in range(5))

        def __init__(self, _path: str) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def list_files(self) -> list[str]:
            return [f"part-{index}.txt" for index in range(5)]

        def block_index_of(self, name: str) -> int:
            return int(name.removeprefix("part-").removesuffix(".txt"))

        def read_file(self, _name: str) -> bytes:
            nonlocal read_calls
            read_calls += 1
            return b"x" * member_size

    monkeypatch.setattr(save_module, "MPQArchive", FakeArchive)

    # When: named text is collected for evidence.
    _ = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: only members fitting the shared 8 MiB budget are decompressed.
    assert read_calls == 2


def test_mpq_binary_members_consume_the_aggregate_decompression_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: named members decompress successfully but are not readable text.
    save = tmp_path / "profile.sav"
    save.write_bytes(b"MPQ\x1a" + b"\0" * 64)
    save_module = importlib.import_module("w3xtool.real_save_files")
    member_size = 3 * 1024 * 1024
    read_calls = 0

    class Block:
        file_size = member_size

    class FakeArchive:
        block_table = tuple(Block() for _index in range(5))

        def __init__(self, _path: str) -> None:
            return None

        def __enter__(self):
            return self

        def __exit__(self, *_args) -> None:
            return None

        def list_files(self) -> list[str]:
            return [f"part-{index}.bin" for index in range(5)]

        def block_index_of(self, name: str) -> int:
            return int(name.removeprefix("part-").removesuffix(".bin"))

        def read_file(self, _name: str) -> bytes:
            nonlocal read_calls
            read_calls += 1
            return b"\0" * member_size

    monkeypatch.setattr(save_module, "MPQArchive", FakeArchive)

    # When: the analyzer rejects each member as binary after decompression.
    _ = save_module.analyze_real_save_path(save, _map_with_save_contract())

    # Then: binary payloads still consume the same aggregate allocation budget.
    assert read_calls == 2
