"""Actual public save output, category-qualified correlation and stable source bytes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
import sys

import pytest

from gametool.api import GameObject, MapData
from gametool.dev_test import create_test_environment
from gametool.real_save_files import analyze_real_save_path, format_real_save_report_tsv
from tests.save_structure_fixture import (
    cache_bytes,
    container_bytes,
    embedded_cache,
    hero_bytes,
)


def _definitions() -> MapData:
    objects: dict[str, list[GameObject]] = {}
    for category, ext, code, name in (
        ("单位", "w3u", "H001", "hero"),
        ("物品", "w3t", "H001", "same-code item"),
        ("技能", "w3a", "A001", "ability"),
        ("物品", "w3t", "I001", "item"),
    ):
        objects.setdefault(category, []).append(
            GameObject(category, ext, code, code, name, True)
        )
    return MapData(
        path="map.w3x",
        name="map",
        objects=objects,
        obj_index={"H001": objects["物品"][-1]},
    )


@pytest.mark.parametrize("embedded", (False, True))
def test_saved_fields_are_category_qualified_and_inputs_stay_unchanged(
    tmp_path: Path, embedded: bool
) -> None:
    raw = cache_bytes(((), (), (), (("saved hero", hero_bytes("reforged")),), ()))
    path = tmp_path / ("slot.w3z" if embedded else "Campaigns.w3v")
    blob = container_bytes(
        embedded_cache(raw) if embedded else raw, chunks=300, crc_header=True
    )
    path.write_bytes(blob)
    before = (
        hashlib.sha256(blob).digest(),
        path.stat().st_mtime_ns,
        path.stat().st_size,
    )
    report = analyze_real_save_path(path, _definitions())
    assert report.map_path == "map.w3x"
    record = report.files[0]
    assert record.caches[0].complete
    assert record.container is not None
    hero_matches = [
        match
        for match in record.object_matches
        if match.code == "H001" and match.source
    ]
    assert len(hero_matches) == 1
    assert hero_matches[0].category == "单位" and hero_matches[0].name == "hero"
    assert "::decompressed" in hero_matches[0].source
    value = record.caches[0].fields[0].value
    assert isinstance(value, dict)
    assert value["experience"] == 23456
    assert (
        json.loads(json.dumps(report.to_dict(), allow_nan=False))["files"][0]["caches"][
            0
        ]["fields"][0]["type"]
        == "unit"
    )
    assert "raw_secondary_id" in format_real_save_report_tsv(report)
    assert (
        hashlib.sha256(path.read_bytes()).digest(),
        path.stat().st_mtime_ns,
        path.stat().st_size,
    ) == before


def test_named_mpq_members_keep_independent_encoding_offsets_and_cache_records(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gametool.real_save_files as module

    raw = cache_bytes(((), (), (), (("hero", hero_bytes("classic")),), ()))
    text = b"\xef\xbb\xbfPreload('-load CODE123')"
    members = {"Campaigns.w3v": raw, "nested/war3map.lua": text}

    class Archive:
        def __init__(self, _path: str) -> None:
            pass

        def __enter__(self) -> Archive:
            return self

        def __exit__(self, *_args: object) -> None:
            pass

        def list_files(self) -> list[str]:
            return list(members)

        def block_index_of(self, _name: str) -> int:
            return 0

        def read_file(self, name: str) -> bytes:
            return members[name]

    monkeypatch.setattr(module, "MPQArchive", Archive)
    source = tmp_path / "archive.sav"
    source.write_bytes(b"MPQ\x1a" + b"\0" * 40)
    record = analyze_real_save_path(source, _definitions()).files[0]
    assert len(record.members) == 2
    assert record.members[0].caches[0].complete
    code = record.members[1].codes[0]
    assert code.source == "archive.sav::nested/war3map.lua"
    assert text[code.byte_offset : code.byte_end] == code.raw.encode()


def test_public_save_json_uses_existing_real_map_fixture_in_private_cache(
    tmp_path: Path,
) -> None:
    root = Path(__file__).resolve().parents[1]
    map_path = root / "tests/fixtures/maps/war3net-map-script-builder.w3x"
    save = tmp_path / "Campaigns.w3v"
    save.write_bytes(cache_bytes(((), (), (), (("hero", hero_bytes("classic")),), ())))
    output = tmp_path / "report.json"
    result = subprocess.run(
        (
            sys.executable,
            "-X",
            "utf8",
            str(root / "main.py"),
            "save",
            "--map",
            str(map_path),
            "--save",
            str(save),
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
    report = json.loads(output.read_text(encoding="utf-8"))
    field = report["files"][0]["caches"][0]["fields"][0]
    assert field["value"]["unit_id"] == "H001"
    assert field["offset"] > 0


def test_source_change_before_delivery_is_diagnostic_not_stale_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import gametool.real_save_files as module

    source = tmp_path / "profile.pld"
    source.write_text('Preload("-load BEFORE123")', encoding="utf-8")
    original = module._analyze_file

    def changed(
        path: Path,
        relative: str,
        payload: bytes,
        expected_keys: tuple[str, ...],
        md: MapData,
        ancestors: frozenset[str] = frozenset(),
        *,
        text_encoding: str = "auto",
    ) -> module.RealSaveFile:
        result = original(
            path,
            relative,
            payload,
            expected_keys,
            md,
            ancestors,
            text_encoding=text_encoding,
        )
        source.write_text('Preload("-load AFTER12345")', encoding="utf-8")
        return result

    monkeypatch.setattr(module, "_analyze_file", changed)
    report = analyze_real_save_path(source, _definitions())
    assert report.files == ()
    assert any("交付前改变" in note for note in report.warnings)


def test_arbitrary_saved_bytes_never_become_hero_fields_without_cache_structure(
    tmp_path: Path,
) -> None:
    source = tmp_path / "slot.w3z"
    source.write_bytes(
        container_bytes(
            b"prefix H001 Campaigns.w3v\0" + hero_bytes("reforged"), chunks=128
        )
    )
    record = analyze_real_save_path(source, _definitions()).files[0]
    assert record.caches == ()


def test_nested_archive_report_serialization_has_no_python_recursion_ceiling() -> None:
    from gametool.real_save_files import RealSaveFile, SaveFileKind

    record = RealSaveFile("leaf", SaveFileKind.BINARY, 0, "sha", (), (), (), "unknown")
    for index in range(1100):
        record = RealSaveFile(
            str(index),
            SaveFileKind.MPQ,
            0,
            "sha",
            (),
            (),
            (),
            "named members",
            members=(record,),
        )
    result = json.loads(json.dumps(record.to_dict(), allow_nan=False))
    assert result["member_tree_encoding"] == "flat-parent-index"
    assert len(result["members"]) == 1100
    assert result["members"][-1]["source"] == "leaf"
    assert result["members"][-1]["parent_member_index"] == 1098
