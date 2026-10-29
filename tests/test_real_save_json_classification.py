"""Public save analysis classifies JSON without numeric conversion quotas."""

import hashlib
from pathlib import Path

import pytest

from gametool.real_save_files import SaveFileKind, analyze_real_save_path


def _snapshot(path: Path):
    metadata = path.stat()
    return (
        path.read_bytes(),
        metadata.st_dev,
        metadata.st_ino,
        metadata.st_size,
        metadata.st_mtime_ns,
        metadata.st_ctime_ns,
    )


def test_public_single_save_keeps_long_numeric_token_and_duplicate_json_keys(tmp_path):
    source = tmp_path / "quantity.json"
    text = (
        '{"数量":' + "9" * 5000 + ',"名称":"原名","名称":"另名","扩展":{"all":[1,2,3]}}'
    )
    raw = text.encode("utf-8")
    source.write_bytes(raw)
    before = _snapshot(source)
    report = analyze_real_save_path(source)
    assert report.complete
    assert len(report.files) == 1
    record = report.files[0]
    assert record.kind is SaveFileKind.JSON
    assert record.raw_text == text
    assert record.sha256 == hashlib.sha256(raw).hexdigest()
    assert record.complete and record.source_stable
    assert record.to_dict()["raw_text"] == text
    assert _snapshot(source) == before


def test_public_directory_continues_after_large_json_and_retains_invalid_json(tmp_path):
    files = {
        "01-quantity.json": '{"quantity":' + "8" * 5000 + "}",
        "02-invalid.json": '{"unfinished":[1,2,3]',
        "03-note.txt": "complete later file",
    }
    for name, text in files.items():
        (tmp_path / name).write_bytes(text.encode("utf-8"))
    before = {name: _snapshot(tmp_path / name) for name in files}
    report = analyze_real_save_path(tmp_path)
    assert report.inventory_complete
    assert not report.complete
    records = {record.relative_path: record for record in report.files}
    assert set(records) == set(files)
    assert records["01-quantity.json"].kind is SaveFileKind.JSON
    assert records["02-invalid.json"].kind is SaveFileKind.TEXT
    assert not records["02-invalid.json"].complete
    assert records["02-invalid.json"].diagnostics
    assert records["03-note.txt"].kind is SaveFileKind.TEXT
    assert all(records[name].raw_text == text for name, text in files.items())
    assert {name: _snapshot(tmp_path / name) for name in files} == before


@pytest.mark.parametrize(
    ("name", "text", "kind"),
    [
        ("settings.ini", "[profile]\nvalue=1", SaveFileKind.INI),
        ("settings.cfg", "value=1", SaveFileKind.INI),
        ("profile.pld", 'call Preload("-load ABCD")', SaveFileKind.PRELOAD),
        ("notes.txt", '{"quantity":123}', SaveFileKind.TEXT),
    ],
)
def test_non_json_file_classification_is_unchanged(tmp_path, name, text, kind):
    source = tmp_path / name
    source.write_bytes(text.encode("utf-8"))
    record = analyze_real_save_path(source).files[0]
    assert record.kind is kind
    assert record.raw_text == text
