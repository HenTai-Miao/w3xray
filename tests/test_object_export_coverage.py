"""Selected empty object exports remain distinct from unknown source coverage."""

from __future__ import annotations

import csv
import json
import os
from pathlib import Path

import pytest

from gametool.archive_source import PathArchiveSource
from gametool.extraction_profile import ALL_CATEGORIES, ExtractionProfile
from gametool.knowledge_pack import write_knowledge_pack_report
from gametool.knowledge_results import KnowledgeWriteStatus
from gametool.map_data import MapData
from gametool.map_loader import load_map
from gametool.object_export_coverage import (
    OBJECT_COVERAGE_COLUMN,
    OBJECT_COVERAGE_FILE,
    format_object_export_coverage,
    object_export_coverage_bytes,
)
from gametool.pack_query_cli import execute_pack_query
from gametool.pack_query_objects import OBJECT_TABLES
from gametool.pack_query_options import PackQueryCliOptions
from gametool.reference_cli import run_reference_cli
from gametool.reference_sources import PackReferenceSources
from gametool.safe_output_models import SafeWriteResult, SafeWriteStatus
from tests.skin_layers_fixture import mpq, object_file


def _publish(
    md: MapData,
    destination: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    objects: bool = True,
) -> None:
    # The focused export never consults the user's installed game or profile.
    monkeypatch.setattr(
        "gametool.knowledge_pack_contents.discover_game_data_path", lambda: None
    )
    profile = ExtractionProfile(
        {category: category == "objects" and objects for category in ALL_CATEGORIES}
    )
    report = write_knowledge_pack_report(md, str(destination), profile=profile)
    assert report.status is KnowledgeWriteStatus.COMPLETE


@pytest.mark.parametrize("has_item", (False, True))
def test_complete_selected_exports_write_all_empty_category_headers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    has_item: bool,
) -> None:
    files = (
        {"war3map.w3t": object_file("w3t", (("unam", "Only item", 0, 0),))}
        if has_item
        else {}
    )
    source = tmp_path / "complete.w3x"
    source.write_bytes(mpq(files))
    md = load_map(str(source))
    pack = tmp_path / "pack"
    try:
        assert not md.diagnostics
        counts = md.category_counts()
        _publish(md, pack, monkeypatch)
    finally:
        md.close()

    for category in OBJECT_TABLES:
        with (pack / "对象ID" / f"{category}.tsv").open(
            encoding="utf-8", newline=""
        ) as handle:
            rows = list(csv.reader(handle, delimiter="\t"))
        assert rows[0] == [
            "分类",
            "ID",
            "10进制",
            "基础ID",
            "名称",
            "自定义",
            "说明",
            OBJECT_COVERAGE_COLUMN,
        ]
        assert len(rows) == counts.get(category, 0) + 1

    assert run_reference_cli(("--pack", str(pack), "--kind", "objects", "--json")) == 0
    reference = json.loads(capsys.readouterr().out)
    assert reference["catalog_complete"] is True
    assert reference["diagnostics"] == []

    stats = execute_pack_query(PackQueryCliOptions(str(pack), "stats", ""))
    assert stats.exit_code == 0
    for category in OBJECT_TABLES:
        count = counts.get(category, 0)
        assert f"{category}: {count} 行" in stats.render()
    heroes = execute_pack_query(PackQueryCliOptions(str(pack), "heroes", ""))
    assert "本次可确认英雄对象记录共 0 项" in heroes.render()
    assert not any(note.startswith("[⚠") for note in heroes.diagnostics)


def test_profile_disabled_objects_remain_unknown_after_export(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "complete.w3x"
    source.write_bytes(mpq({}))
    md = load_map(str(source))
    pack = tmp_path / "pack"
    try:
        _publish(md, pack, monkeypatch, objects=False)
    finally:
        md.close()
    assert not (pack / "对象ID").exists()
    assert run_reference_cli(("--pack", str(pack), "--json")) == 2
    reference = json.loads(capsys.readouterr().out)
    assert reference["catalog_complete"] is False
    assert any("未记录此表" in note for note in reference["diagnostics"])
    units = execute_pack_query(PackQueryCliOptions(str(pack), "units", ""))
    assert units.exit_code == 2
    assert "提取配置未选择对象导出" in units.render()
    stats = execute_pack_query(PackQueryCliOptions(str(pack), "stats", ""))
    assert "单位: 0 条已确认记录（完整性未确认）" in stats.render()


def test_corrupt_object_source_export_cannot_certify_empty_category(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "partial.w3x"
    source.write_bytes(mpq({"war3map.w3u": b"\x02\0\0\0"}))
    md = load_map(str(source))
    pack = tmp_path / "pack"
    try:
        assert any(note.source == "war3map.w3u" for note in md.diagnostics)
        _publish(md, pack, monkeypatch)
    finally:
        md.close()
    assert run_reference_cli(("--pack", str(pack), "--json")) == 2
    reference = json.loads(capsys.readouterr().out)
    assert reference["catalog_complete"] is False
    assert reference["diagnostics"]
    assert any("war3map.w3u" in note for note in reference["diagnostics"])
    units = execute_pack_query(PackQueryCliOptions(str(pack), "units", ""))
    assert units.exit_code == 2
    assert "完整地图总量" in units.render()
    assert "war3map.w3u" in units.render()


@pytest.mark.parametrize("has_source_reference", (False, True))
def test_unread_source_export_preserves_unknown_coverage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    has_source_reference: bool,
) -> None:
    md = MapData(str(tmp_path / "unread.w3x"), "Unread source")
    if has_source_reference:
        md.archive_source = PathArchiveSource(md.path)
    pack = tmp_path / "pack"
    _publish(md, pack, monkeypatch)
    assert run_reference_cli(("--pack", str(pack), "--json")) == 2
    reference = json.loads(capsys.readouterr().out)
    assert reference["catalog_complete"] is False
    reason = "未记录归档读取台账" if has_source_reference else "未记录已加载的归档来源"
    assert any(reason in note for note in reference["diagnostics"])
    stats = execute_pack_query(PackQueryCliOptions(str(pack), "stats", ""))
    for category in OBJECT_TABLES:
        assert f"{category}: 0 条已确认记录（完整性未确认）" in stats.render()


def _empty_pack(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    source = tmp_path / "complete.w3x"
    source.write_bytes(mpq({}))
    md = load_map(str(source))
    pack = tmp_path / "pack"
    try:
        _publish(md, pack, monkeypatch)
    finally:
        md.close()
    return pack


def test_coverage_add_edit_delete_are_fresh_in_queries_and_reference(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    pack = _empty_pack(tmp_path, monkeypatch)
    path = pack / OBJECT_COVERAGE_FILE
    original = path.read_bytes()
    original_stat = path.stat()

    def assert_state(complete: bool) -> None:
        result = execute_pack_query(PackQueryCliOptions(str(pack), "stats", ""))
        assert ("完整性未确认" not in result.render()) is complete
        assert run_reference_cli(("--pack", str(pack), "--json")) == (
            0 if complete else 2
        )
        payload = json.loads(capsys.readouterr().out)
        assert payload["catalog_complete"] is complete

    assert_state(True)
    # Same byte size and restored mtime cannot reuse the previous coverage.
    path.write_bytes(original.replace(b"complete", b"partial ", 1))
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert path.stat().st_size == original_stat.st_size
    assert_state(False)
    path.unlink()
    assert_state(False)
    path.write_bytes(original)
    os.utime(path, ns=(original_stat.st_atime_ns, original_stat.st_mtime_ns))
    assert_state(True)


@pytest.mark.parametrize("operation", ("modify", "delete", "add"))
def test_query_delivery_revalidates_coverage_and_preserves_query_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    from gametool import pack_query_cli as queries

    pack = _empty_pack(tmp_path, monkeypatch)
    path = pack / OBJECT_COVERAGE_FILE
    original = path.read_bytes()
    if operation == "add":
        path.unlink()
    stats_query = queries._QUERIES["stats"]
    memories: list[tuple[Path, str, str]] = []

    def changing_query(directory: Path, query: str, limit: int) -> list[str]:
        result = stats_query(directory, query, limit)
        if operation == "delete":
            path.unlink()
        else:
            path.write_bytes(original + (b"\n" if operation == "modify" else b""))
        return result

    monkeypatch.setitem(queries._QUERIES, "stats", changing_query)
    monkeypatch.setattr(
        queries,
        "_store_last_query",
        lambda pack, command, query: memories.append((pack, command, query)),
    )
    result = execute_pack_query(PackQueryCliOptions(str(pack), "stats", ""))
    assert result.exit_code == 2
    assert "来源覆盖在查询交付前变化" in result.render()
    assert memories == []


@pytest.mark.parametrize("operation", ("modify", "delete", "add"))
def test_reference_delivery_revalidates_complete_coverage_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    operation: str,
) -> None:
    pack = _empty_pack(tmp_path, monkeypatch)
    path = pack / OBJECT_COVERAGE_FILE
    original = path.read_bytes()
    if operation == "add":
        path.unlink()
    verify = PackReferenceSources.verify

    def changing_verify(adapter: PackReferenceSources) -> None:
        if operation == "delete":
            path.unlink()
        else:
            path.write_bytes(original + (b"\n" if operation == "modify" else b""))
        verify(adapter)

    monkeypatch.setattr(PackReferenceSources, "verify", changing_verify)
    assert run_reference_cli(("--pack", str(pack), "--json")) == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["catalog_complete"] is False
    assert any(
        OBJECT_COVERAGE_FILE in note and "目录交付前变化" in note
        for note in payload["diagnostics"]
    )


def test_coverage_selection_states_and_source_diagnostics_are_independent() -> None:
    md = MapData("unread.w3x", "Unread source")
    payload = format_object_export_coverage(md, selected=False).encode("utf-8")
    coverage = object_export_coverage_bytes(payload)
    assert dict(coverage.states) == dict.fromkeys(OBJECT_TABLES, "disabled")
    for category in OBJECT_TABLES:
        notes = coverage.for_table(category)
        assert any(f"{category}: 提取配置未选择" in note for note in notes)
        assert any("未记录已加载的归档来源" in note for note in notes)


def test_legacy_external_pack_still_requires_every_actual_table(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    directory = tmp_path / "对象ID"
    directory.mkdir()
    for category in OBJECT_TABLES:
        (directory / f"{category}.tsv").write_text(
            "分类\tID\t10进制\t基础ID\t名称\t自定义\t说明\n", encoding="utf-8"
        )
    (tmp_path / "对象字段.tsv").write_text(
        "分类\tID\t名称\t字段键\t字段名\t值\t来源\n", encoding="utf-8"
    )
    assert run_reference_cli(("--pack", str(tmp_path), "--json")) == 0
    complete = json.loads(capsys.readouterr().out)
    assert complete["catalog_complete"] is True
    assert complete["map_scopes"] == []
    (directory / "英雄.tsv").unlink()
    assert run_reference_cli(("--pack", str(tmp_path), "--json")) == 2
    partial = json.loads(capsys.readouterr().out)
    assert partial["catalog_complete"] is False
    assert any("英雄.tsv" in note for note in partial["diagnostics"])


def test_failed_coverage_publication_never_certifies_empty_tables(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from gametool import knowledge_io

    source = tmp_path / "complete.w3x"
    source.write_bytes(mpq({}))
    md = load_map(str(source))
    pack = tmp_path / "pack"
    write = knowledge_io.write_text_safely

    def fail_coverage(root: str, name: str, text: str) -> SafeWriteResult:
        if name == OBJECT_COVERAGE_FILE:
            return SafeWriteResult(SafeWriteStatus.FAILED, "", 0, "coverage disk full")
        return write(root, name, text)

    monkeypatch.setattr(knowledge_io, "write_text_safely", fail_coverage)
    monkeypatch.setattr(
        "gametool.knowledge_pack_contents.discover_game_data_path", lambda: None
    )
    try:
        report = write_knowledge_pack_report(
            md,
            str(pack),
            profile=ExtractionProfile(
                {category: category == "objects" for category in ALL_CATEGORIES}
            ),
        )
    finally:
        md.close()
    assert report.status is KnowledgeWriteStatus.PARTIAL
    assert report.items_by_path[OBJECT_COVERAGE_FILE].error == "coverage disk full"
    assert not (pack / "对象ID").exists()
    assert run_reference_cli(("--pack", str(pack), "--json")) == 2
    partial = json.loads(capsys.readouterr().out)
    assert partial["catalog_complete"] is False
    assert any(OBJECT_COVERAGE_FILE in note for note in partial["diagnostics"])
