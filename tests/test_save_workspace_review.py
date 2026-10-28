"""Independent regressions for source coverage, literal states and final publication."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import gametool.real_save_files as save_files
import gametool.save_report_query as reports
from gametool.real_save_cli import run_real_save_cli
from tests.save_structure_fixture import (
    cache_bytes,
    container_bytes,
    embedded_cache,
    u32,
)


def test_embedded_cache_never_hides_unknown_prefix_frame_or_tail(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = cache_bytes(((("score", u32(7)),), (), (), (), ()))
    prefix, tail = b"\0UNKNOWN-PREFIX\0", b"\xffUNKNOWN-TAIL\0"
    raw = prefix + embedded_cache(cache) + tail
    source = tmp_path / "framed.w3z"
    source.write_bytes(container_bytes(raw, chunks=128))
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    evidence = record.caches[0]
    assert evidence.complete and evidence.fields[0].value == 7
    assert not report.complete and not record.complete
    assert report.inventory_complete and record.source_stable
    actual = [(row["offset"], row["end"]) for row in record.unknown_ranges]
    assert actual == [
        (0, len(prefix)),
        (len(prefix) + 8, len(prefix) + 40),
        (evidence.offset + evidence.consumed, len(raw)),
    ]
    for unknown in record.unknown_ranges:
        start, end = unknown["offset"], unknown["end"]
        assert isinstance(start, int) and isinstance(end, int)
        assert unknown["raw_hex"] == raw[start:end].hex()
        assert unknown["sha256"] == hashlib.sha256(raw[start:end]).hexdigest()
        origin = unknown["source"]
        assert isinstance(origin, str) and origin.endswith("::decompressed")
    selected = reports.select_save_report(report, "nothing-matches")
    assert selected.files == () and any(
        "unknown" in note for note in selected.diagnostics
    )
    output = tmp_path / "report.json"
    assert (
        run_real_save_cli(
            ("--save", str(source), "--output", str(output), "--format", "json")
        )
        == 2
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert value["files"][0]["unknown_ranges"]
    assert value["files"][0]["caches"][0]["fields"][0]["value"] == 7
    assert "未完成" in capsys.readouterr().out


def test_unknown_literal_escape_makes_file_report_and_cli_incomplete(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "bad-escape.j"
    raw = rb'call Preload("-load ABC\q123")'
    source.write_bytes(raw)
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert not record.complete and not report.complete
    assert record.raw_text == raw.decode()
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert len(record.text_carriers) == len(record.codes) == 1
    assert not record.text_carriers[0].literal_complete
    assert not record.codes[0].literal_complete
    assert record.text_carriers[0].state == "unknown-text"
    selected = reports.select_save_report(report)
    assert any("unknown string escape" in note for note in selected.diagnostics)
    output = tmp_path / "report.json"
    assert (
        run_real_save_cli(
            ("--save", str(source), "--output", str(output), "--format", "json")
        )
        == 2
    )
    value = json.loads(output.read_text(encoding="utf-8"))
    assert (
        not value["complete"]
        and not value["files"][0]["text_carriers"][0]["literal_complete"]
    )
    assert source.read_bytes() == raw
    assert "未完成" in capsys.readouterr().out


@pytest.mark.parametrize("format", ("json", "tsv", "md"))
def test_second_render_mutation_refuses_publication_without_touching_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, format: str
) -> None:
    source = tmp_path / "source"
    source.mkdir()
    first, second = source / "a.txt", source / "b.txt"
    first.write_text("a-original", encoding="utf-8")
    second.write_text("b-original", encoding="utf-8")
    selected = reports.select_save_report(save_files.analyze_real_save_path(source))
    original = reports.save_report_payload
    rendered = 0

    def mutate(selection: reports.SaveReportSelection, kind: str = "json") -> str:
        nonlocal rendered
        rendered += 1
        assert rendered <= 2
        payload = original(selection, kind)
        (first if rendered == 1 else second).write_text(
            f"changed after render {rendered}", encoding="utf-8"
        )
        return payload

    monkeypatch.setattr(reports, "save_report_payload", mutate)
    output = tmp_path / f"report.{format}"
    output.write_bytes(b"original report remains public")
    with pytest.raises(ValueError, match="持续变化.*拒绝发布"):
        reports.write_save_report(selected, output, format)
    assert rendered == 2
    assert output.read_bytes() == b"original report remains public"
    assert first.read_text(encoding="utf-8") == "changed after render 1"
    assert second.read_text(encoding="utf-8") == "changed after render 2"
    assert selected.files[0].raw_text == "a-original"
    assert selected.files[1].raw_text == "b-original"


@pytest.mark.parametrize(
    "title",
    (
        "PreloadFiles",
        'call Preload("-load ABC123")',
        "function PreloadFiles takes nothing returns nothing",
    ),
)
def test_valid_json_has_priority_over_preload_words(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], title: str
) -> None:
    source = tmp_path / "profile.json"
    raw = json.dumps({"title": title}, ensure_ascii=False).encode()
    source.write_bytes(raw)
    report = save_files.analyze_real_save_path(source)
    record = report.files[0]
    assert record.kind is save_files.SaveFileKind.JSON
    assert record.complete and report.complete
    assert record.raw_text == raw.decode()
    assert not reports.select_save_report(report).diagnostics
    output = tmp_path / "report.json"
    assert (
        run_real_save_cli(
            ("--save", str(source), "--output", str(output), "--format", "json")
        )
        == 0
    )
    assert json.loads(output.read_text(encoding="utf-8"))["files"][0]["kind"] == "json"
    capsys.readouterr()


def test_preload_words_inside_plain_strings_and_comments_are_not_format_proof(
    tmp_path: Path,
) -> None:
    source = tmp_path / "mentions.txt"
    source.write_text('"PreloadFiles"\n// call Preload("words")\n', encoding="utf-8")
    record = save_files.analyze_real_save_path(source).files[0]
    assert record.kind is save_files.SaveFileKind.TEXT
    assert record.raw_text == source.read_bytes().decode("utf-8")
