"""Public regressions for independently confirmed save review findings."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from typing import Any, cast

import pytest

from gametool.api import MapData
from gametool.dev_test import create_test_environment
from gametool.real_save_files import analyze_real_save_path
from gametool.save_code_cli import run_save_code_cli
from gametool.save_container import inspect_save_container, unpack_save_container
from tests.save_structure_fixture import cache_bytes, container_bytes, u32

_ROOT = Path(__file__).resolve().parents[1]
_MAP = _ROOT / "tests/fixtures/maps/war3net-map-script-builder.w3x"


@pytest.mark.parametrize("version,crc_offset", ((0, 60), (1, 64)))
@pytest.mark.parametrize("extension", (b"", b"opaque-extra-header"))
def test_crc_location_and_span_follow_the_encoded_header_version(
    version: int, crc_offset: int, extension: bytes
) -> None:
    # Primary proof: https://raw.githubusercontent.com/nielsAD/gowarcraft3/master/file/w3g/header.go
    # DecodeHeader lines 51-98: fixed read n=64/68; CRC at n-4 over buf[:n].
    raw = b"saved cache bytes"
    blob = container_bytes(
        raw,
        shape="<HHI",
        chunks=100,
        crc_header=True,
        header_version=version,
        header_extension=extension,
    )
    result = inspect_save_container(blob)
    assert result.complete and result.header_checksum_ok
    assert result.header_checksum_offset == crc_offset
    assert result.header_checksum_span == crc_offset + 4
    assert result.header is not None and result.header.subheader.endswith(extension)
    assert unpack_save_container(blob).raw == raw
    damaged = bytearray(blob)
    damaged[crc_offset] ^= 1
    invalid = inspect_save_container(bytes(damaged))
    assert not invalid.complete and invalid.raw == raw
    assert invalid.header_checksum_ok is False


def _save_json(tmp_path: Path, source: Path) -> dict[str, Any]:
    output = tmp_path / "report.json"
    result = subprocess.run(
        (
            sys.executable,
            "-X",
            "utf8",
            str(_ROOT / "main.py"),
            "save",
            "--map",
            str(_MAP),
            "--save",
            str(source),
            "--output",
            str(output),
            "--format",
            "json",
        ),
        env=create_test_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return cast(dict[str, Any], json.loads(output.read_text(encoding="utf-8")))


def test_public_save_accepts_standard_v0_crc_and_keeps_saved_cache(
    tmp_path: Path,
) -> None:
    raw = cache_bytes(((("gold", u32(42)),), (), (), (), ()))
    source = tmp_path / "Campaigns.w3v"
    source.write_bytes(
        container_bytes(
            raw, shape="<HHI", chunks=200, crc_header=True, header_version=0
        )
    )
    report = _save_json(tmp_path, source)
    record = report["files"][0]
    assert record["container"]["header"]["checksum_offset"] == 60
    assert record["container"]["header"]["checksum_ok"]
    assert record["caches"][0]["complete"]
    assert record["caches"][0]["fields"][0]["value"] == 42


@pytest.mark.parametrize("reserved_is_magic", (False, True))
def test_public_raw_cache_keeps_records_when_values_or_reserved_word_contain_mpq_magic(
    tmp_path: Path, reserved_is_magic: bool
) -> None:
    raw = bytearray(
        cache_bytes(((("gold", u32(42)),), (), (), (), (("note", b"MPQ\x1a\0"),)))
    )
    if reserved_is_magic:
        raw[:4] = b"MPQ\x1a"
    source = tmp_path / "Campaigns.w3v"
    source.write_bytes(raw)
    report = _save_json(tmp_path, source)
    record = report["files"][0]
    assert record["kind"] == "gamecache"
    assert record["caches"][0]["complete"]
    assert [field["value"] for field in record["caches"][0]["fields"]] == [
        42,
        "MPQ\x1a",
    ]
    assert source.read_bytes() == raw


def test_actual_archive_layout_can_be_identified_under_a_cache_suffix(
    tmp_path: Path,
) -> None:
    source = tmp_path / "archive.w3v"
    source.write_bytes(_MAP.read_bytes())
    record = analyze_real_save_path(source, MapData(path="map", name="map")).files[0]
    assert record.kind.value == "mpq" and record.members


@pytest.mark.parametrize(
    "literal,expected",
    ((r"-load \xC3\xA9ABC", "-load éABC"), (r"-load \195\169ABC", "-load éABC")),
)
def test_public_savecodes_decodes_lua_byte_sequences_in_actual_utf8_source(
    tmp_path: Path, literal: str, expected: str
) -> None:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "war3map.lua").write_text(f'Preload("{literal}")', encoding="utf-8")
    result = subprocess.run(
        (
            sys.executable,
            "-X",
            "utf8",
            str(_ROOT / "main.py"),
            "savecodes",
            str(pack),
            "--json",
        ),
        env=create_test_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["codes"][0]["code"] == expected
    assert report["text_carriers"][0]["literal_complete"]
    assert report["text_carriers"][0]["literal_bytes_hex"] == expected.encode().hex()


def test_public_savecodes_keeps_invalid_lua_bytes_raw_and_diagnostic(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "war3map.lua").write_text(r'Preload("-load \xFFABC")', encoding="utf-8")
    assert run_save_code_cli((str(tmp_path), "--json")) == 2
    report = json.loads(capsys.readouterr().out)
    carrier = report["text_carriers"][0]
    assert carrier["state"] == "unknown-text" and not carrier["literal_complete"]
    assert carrier["literal_bytes_hex"] == b"-load \xffABC".hex()
    assert carrier["raw"] == r'"-load \xFFABC"'
    assert "ÿ" not in carrier["text"]
    assert report["diagnostics"]


def _directory_link(link: Path, target: Path) -> None:
    if os.name == "nt":
        result = subprocess.run(
            ("cmd", "/c", "mklink", "/J", str(link), str(target)),
            capture_output=True,
            text=True,
            check=False,
        )
        assert result.returncode == 0, result.stderr
        assert link.is_junction()
    else:
        link.symlink_to(target, target_is_directory=True)


@pytest.mark.parametrize("root_link", (False, True))
def test_public_savecodes_rejects_junctions_before_reading_outside_pack(
    tmp_path: Path, root_link: bool
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "profile.j").write_text(
        'call Preload("-load OUTSIDE123")', encoding="utf-8"
    )
    pack = tmp_path / "pack"
    if root_link:
        _directory_link(pack, outside)
    else:
        pack.mkdir()
        _directory_link(pack / "linked", outside)
    result = subprocess.run(
        (
            sys.executable,
            "-X",
            "utf8",
            str(_ROOT / "main.py"),
            "savecodes",
            str(pack),
            "--json",
        ),
        env=create_test_environment(),
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
        timeout=30,
    )
    assert result.returncode == 2, result.stderr
    report = json.loads(result.stdout)
    assert report["scanned"] == report["total"] == 0
    assert report["text_carriers"] == []
    assert "reparse point" in " ".join(report["diagnostics"])
    assert "OUTSIDE123" not in result.stdout
    saves = analyze_real_save_path(pack, MapData(path="map", name="map"))
    assert saves.files == () and saves.warnings
