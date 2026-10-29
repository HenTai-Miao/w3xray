"""Call results prove full byte and source membership stability before delivery."""

import os
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from gametool import pack_query_script_calls as calls
from gametool.pack_query_script_snapshot import capture_script_pack


def _source(pack: Path) -> Path:
    path = pack / "脚本原始文本" / "war3map.lua"
    path.parent.mkdir()
    path.write_bytes(b"KillUnit(unit1)")
    return path


def _during_render(monkeypatch: pytest.MonkeyPatch, change) -> None:
    original = calls._render_records

    def wrapped(*args, **kwargs):
        output = original(*args, **kwargs)
        change()
        return output

    monkeypatch.setattr(calls, "_render_records", wrapped)


def test_source_same_size_same_mtime_mutation_is_detected_after_render(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _source(tmp_path)
    before = path.stat()

    def change() -> None:
        path.write_bytes(b"KillUnit(unit2)")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    _during_render(monkeypatch, change)
    result = calls.query_script_calls(tmp_path, "")
    assert result.calls[0].arguments == ("unit1",)
    assert result.input_error and not result.source_stable
    assert result.script_coverage.complete is False
    assert any(note.code == "snapshot.changed" for note in result.diagnostics)


@pytest.mark.parametrize(
    "relative",
    [
        "脚本调用参数索引.tsv",
        "地图信息.txt",
        "脚本清单.txt",
        "组件诊断.tsv",
        "未知文件/加密脚本检测.txt",
    ],
)
def test_every_metadata_and_index_byte_is_revalidated_even_with_preserved_stat(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    _source(tmp_path)
    path = tmp_path / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"before")
    before = path.stat()

    def change() -> None:
        path.write_bytes(b"after!")
        os.utime(path, ns=(before.st_atime_ns, before.st_mtime_ns))

    _during_render(monkeypatch, change)
    result = calls.query_script_calls(tmp_path, "")
    assert result.input_error and not result.source_stable
    assert any(
        note.source == relative and note.code == "snapshot.changed"
        for note in result.diagnostics
    )


@pytest.mark.parametrize(
    "relative",
    [
        "脚本调用参数索引.tsv",
        "地图信息.txt",
        "脚本清单.txt",
        "组件诊断.tsv",
        "未知文件/加密脚本检测.txt",
        "脚本原始文本/new.lua",
        "脚本可读文本/new.lua",
    ],
)
def test_missing_to_present_metadata_or_sources_cannot_escape_snapshot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: str
) -> None:
    _source(tmp_path)

    def change() -> None:
        path = tmp_path / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("GetLocalPlayer()", encoding="utf-8")

    _during_render(monkeypatch, change)
    result = calls.query_script_calls(tmp_path, "")
    assert result.input_error and not result.source_stable
    assert result.total == 1


def test_disappearing_original_boundary_does_not_downgrade_to_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _source(tmp_path)
    readable = tmp_path / "脚本可读文本" / "war3map.lua"
    readable.parent.mkdir()
    readable.write_text("GetLocalPlayer()", encoding="utf-8")

    def change() -> None:
        original.unlink()
        original.parent.rmdir()

    _during_render(monkeypatch, change)
    result = calls.query_script_calls(tmp_path, "")
    assert result.calls[0].callee == "KillUnit"
    assert result.input_error and not result.source_stable


def test_stable_snapshot_captures_both_directories_and_missing_reports(
    tmp_path: Path,
) -> None:
    original = _source(tmp_path)
    snapshot = capture_script_pack(tmp_path)
    assert snapshot.original and snapshot.source_directory == "脚本原始文本"
    assert snapshot.verify() == ()
    files = {item.relative: item for item in snapshot.files}
    assert files["脚本原始文本/war3map.lua"].payload == original.read_bytes()
    assert files["脚本调用参数索引.tsv"].state == "missing"
    assert files["未知文件/加密脚本检测.txt"].state == "missing"


def test_read_error_is_uncertainty_and_does_not_use_readable_copy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = _source(tmp_path)
    readable = tmp_path / "脚本可读文本" / "war3map.lua"
    readable.parent.mkdir()
    readable.write_text("GetLocalPlayer()", encoding="utf-8")
    real_open = Path.open

    def failing(path, *args, **kwargs):
        if path == original:
            raise PermissionError("synthetic source failure")
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", failing)
    result = calls.query_script_calls(tmp_path, "")
    assert result.total == 0 and not result.input_error
    assert result.source_stable and result.script_coverage.complete is False
    assert "synthetic source failure" in "\n".join(result.lines)


def test_final_campaign_stage_revalidates_earlier_section_after_later_work(
    tmp_path: Path,
) -> None:
    original = _source(tmp_path)
    first = calls.query_script_calls(tmp_path, "")
    assert first.source_stable and first.snapshot_identity is not None
    assert first.snapshot_identity.pack == str(tmp_path.absolute())
    json.loads(json.dumps(asdict(first.snapshot_identity), ensure_ascii=False))
    before = original.stat()
    child = tmp_path / "子地图" / "child"
    child.mkdir(parents=True)
    _source(child)
    later = calls.query_script_calls(child, "")
    assert later.source_stable
    original.write_bytes(b"KillUnit(unit2)")
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns))
    delivered = calls.revalidate_script_calls(first)
    assert delivered.calls == first.calls and delivered.total == first.total
    assert delivered.snapshot_identity == first.snapshot_identity
    assert delivered.input_error and not delivered.source_stable
    assert delivered.script_coverage.complete is False
    # Returning the bytes to their former value cannot make a diagnosed result
    # retroactively successful or remove its earlier source-change evidence.
    original.write_bytes(b"KillUnit(unit1)")
    os.utime(original, ns=(before.st_atime_ns, before.st_mtime_ns))
    retried = calls.revalidate_script_calls(delivered)
    assert retried.input_error and not retried.source_stable
    assert retried.diagnostics == delivered.diagnostics


def test_final_campaign_stage_detects_metadata_appearance_and_empty_results(
    tmp_path: Path,
) -> None:
    _source(tmp_path)
    original = calls.query_script_calls(tmp_path, "does-not-match")
    assert original.total == 0 and original.source_stable
    (tmp_path / "脚本清单.txt").write_text("脚本文件：0\n", encoding="utf-8")
    delivered = calls.revalidate_script_calls(original)
    assert (
        delivered.total == 0 and delivered.input_error and not delivered.source_stable
    )
    assert delivered.snapshot_identity == original.snapshot_identity
