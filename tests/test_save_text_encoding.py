"""Explicit UTF-16 save text, exact source bytes and complete offline entrypoints."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

from gametool.real_save_cli import run_real_save_cli
from gametool.real_save_files import SaveFileKind, analyze_real_save_path
from gametool.save_code_cli import run_save_code_cli
from gametool.save_codes import decode_save_text, extract_save_codes_bytes
from gametool.save_text_encoding import inspect_save_text
from tests.save_structure_fixture import cache_bytes


_TEXT = '存档码: AbCD1234\r\n-load AbCD1234\r\nPreload("!save 中文\U0001f4099876")\r\n'


@pytest.mark.parametrize(
    "encoding,bom",
    (
        ("utf-8", b"\xef\xbb\xbf"),
        ("utf-16-le", b"\xff\xfe"),
        ("utf-16-be", b"\xfe\xff"),
    ),
)
def test_bom_text_is_automatic_lossless_and_offsets_include_bom(
    encoding: str,
    bom: bytes,
) -> None:
    payload = bom + _TEXT.encode(encoding)
    result = inspect_save_text(payload)
    assert result.text == _TEXT and result.encoding == encoding
    assert result.diagnostics == () and result.bom_bytes == len(bom)
    assert result.to_dict(payload)["byte_roundtrip"] is True
    assert (
        bytes.fromhex(str(result.to_dict(payload)["bom_hex"]))
        + result.text.encode(encoding)
        == payload
    )
    for hit in extract_save_codes_bytes(payload):
        assert hit.byte_offset is not None and hit.byte_end is not None
        assert payload[hit.byte_offset : hit.byte_end] == hit.raw.encode(encoding)
        assert hit.source_sha256 == hashlib.sha256(payload).hexdigest()


@pytest.mark.parametrize(
    "encoding,alias",
    (
        ("utf-16-le", "utf-16le"),
        ("utf-16-be", "utf-16be"),
    ),
)
def test_bomless_text_requires_explicit_endian_and_keeps_chinese_and_non_bmp(
    encoding: str,
    alias: str,
) -> None:
    payload = _TEXT.encode(encoding)
    assert decode_save_text(payload) is None
    assert extract_save_codes_bytes(payload) == []
    result = inspect_save_text(payload, alias)
    assert result.text == _TEXT and result.encoding == encoding
    assert result.requested_encoding == encoding and result.bom_bytes == 0
    assert result.text.encode(result.encoding) == payload
    codes = extract_save_codes_bytes(payload, text_encoding=alias)
    assert {code.code for code in codes} == {
        "-load AbCD1234",
        "!save 中文\U0001f4099876",
    }
    for code in codes:
        assert payload[code.byte_offset : code.byte_end] == code.raw.encode(encoding)
        assert bytes.fromhex(code.raw_hex) == payload[code.byte_offset : code.byte_end]


@pytest.mark.parametrize(
    "payload,encoding,note",
    (
        (b"\xff\xfe" + _TEXT.encode("utf-16-le"), "utf-16-be", "BOM"),
        (b"\xfe\xff" + _TEXT.encode("utf-16-be"), "utf-8", "BOM"),
        (b"a\x00b", "utf-16-le", "源字节 2:3"),
        (b"\x00a\x00", "utf-16-be", "源字节 2:3"),
        (b"\x00\xd8", "utf-16-le", "源字节 0:2"),
        (b"\xdc\x00", "utf-16-be", "源字节 0:2"),
        (b"\xff\xfea\x00b", "auto", "源字节 4:5"),
        (b"\xff\xfe\x00\xd8", "auto", "源字节 2:4"),
        (b"\x00\x00\x01\x00", "utf-16-le", "控制字符"),
        (b"\xff\xfe\x00\x00a\x00\x00\x00", "auto", "UTF-32"),
    ),
)
def test_failed_decoding_retains_all_bytes_and_precise_reason(
    tmp_path: Path,
    payload: bytes,
    encoding: str,
    note: str,
) -> None:
    source = tmp_path / "bad.txt"
    source.write_bytes(payload)
    before = source.stat()
    report = analyze_real_save_path(source, text_encoding=encoding)
    record = report.files[0]
    assert not report.complete and report.inventory_complete
    assert record.kind is SaveFileKind.BINARY and record.raw_text is None
    assert record.codes == record.text_carriers == ()
    assert (
        record.encoding == "" and record.sha256 == hashlib.sha256(payload).hexdigest()
    )
    assert any(note in diagnostic for diagnostic in record.diagnostics)
    assert bytes.fromhex(str(record.unknown_ranges[0]["raw_hex"])) == payload
    assert record.text_decoding is not None
    assert record.text_decoding["byte_roundtrip"] is False
    assert (
        source.read_bytes() == payload
        and source.stat().st_mtime_ns == before.st_mtime_ns
    )


@pytest.mark.parametrize(
    "payload",
    (
        b"-\x00l\x00o\x00a\x00d\x00 \x00A\x00B\x00C\x00D\x00",
        b"\x01\x00\xff\x00-load NOTPROVED123",
        b"\x00" * 100 + b"-load BINARY123",
    ),
)
def test_auto_never_uses_nul_distribution_as_text_evidence(payload: bytes) -> None:
    result = inspect_save_text(payload)
    assert result.text is None and result.diagnostics
    assert extract_save_codes_bytes(payload) == []


@pytest.mark.parametrize("encoding", ("utf-16-le", "utf-16-be"))
def test_directory_option_preserves_each_file_and_diagnostics(
    tmp_path: Path,
    encoding: str,
) -> None:
    root = tmp_path / "source"
    (root / "nested").mkdir(parents=True)
    (root / "one.txt").write_bytes(_TEXT.encode(encoding))
    (root / "nested" / "two.log").write_bytes("-load SECOND123".encode(encoding))
    unknown = b"\x00\xd8" if encoding.endswith("le") else b"\xd8\x00"
    (root / "bad.txt").write_bytes(unknown)
    before = {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }
    report = analyze_real_save_path(root, text_encoding=encoding)
    assert not report.complete and report.inventory_complete
    assert report.text_encoding == encoding
    records = {record.relative_path: record for record in report.files}
    assert len(records) == 3
    for name, expected in (("one.txt", _TEXT), ("nested/two.log", "-load SECOND123")):
        record = records[name]
        assert record.complete and record.raw_text == expected
        assert record.text_decoding is not None
        assert record.text_decoding["selection"] == "explicit"
        assert record.raw_text is not None
        assert record.raw_text.encode(record.encoding) == before[Path(name)][0]
    assert (
        bytes.fromhex(str(records["bad.txt"].unknown_ranges[0]["raw_hex"])) == unknown
    )
    assert before == {
        path.relative_to(root): (path.read_bytes(), path.stat().st_mtime_ns)
        for path in root.rglob("*")
        if path.is_file()
    }


@pytest.mark.parametrize("mode", ("file", "directory", "stdin"))
def test_savecodes_cli_encoding_retains_complete_source_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    mode: str,
) -> None:
    source = tmp_path / "utf16.log"
    payload = _TEXT.encode("utf-16-le")
    source.write_bytes(payload)
    if mode == "stdin":
        monkeypatch.setattr(
            sys, "stdin", io.TextIOWrapper(io.BytesIO(payload), encoding="utf-8")
        )
        args = ("--stdin",)
    else:
        args = (str(tmp_path if mode == "directory" else source),)
    assert run_save_code_cli((*args, "--text-encoding", "utf-16le", "--json")) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["text_encoding"] == "utf-16-le" and result["total"] == 2
    evidence = result["sources"][0]
    assert bytes.fromhex(evidence["raw_hex"]) == payload
    assert evidence["raw_text"] == _TEXT
    assert evidence["text_decoding"]["byte_roundtrip"] is True
    assert source.read_bytes() == payload


def test_savecodes_failed_file_does_not_lose_original_bytes(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    source = tmp_path / "partial.txt"
    payload = _TEXT.encode("utf-16-le") + b"\xff"
    source.write_bytes(payload)
    assert run_save_code_cli((str(source), "--encoding", "utf-16-le", "--json")) == 2
    value = json.loads(capsys.readouterr().out)
    assert value["codes"] == value["text_carriers"] == []
    assert bytes.fromhex(value["sources"][0]["raw_hex"]) == payload
    assert value["diagnostics"] and "partial.txt" in value["diagnostics"][0]


@pytest.mark.parametrize("format", ("json", "md", "tsv"))
def test_save_cli_exports_selected_encoding_without_modifying_source(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    format: str,
) -> None:
    source = tmp_path / "source.txt"
    payload = _TEXT.encode("utf-16-be")
    source.write_bytes(payload)
    before = source.stat()
    output = tmp_path / f"report.{format}"
    assert (
        run_real_save_cli(
            (
                "--save",
                str(source),
                "--output",
                str(output),
                "--format",
                format,
                "--text-encoding",
                "utf-16be",
            )
        )
        == 0
    )
    capsys.readouterr()
    text = output.read_text(encoding="utf-8")
    assert "utf-16-be" in text and "AbCD1234" in text and "byte_roundtrip" in text
    if format == "json":
        value = json.loads(text)
        assert value["text_encoding"] == "utf-16-be" and value["complete"]
        assert value["files"][0]["raw_text"] == _TEXT
    assert (
        source.read_bytes() == payload
        and source.stat().st_mtime_ns == before.st_mtime_ns
    )


def test_explicit_text_option_does_not_override_known_binary_gamecache(
    tmp_path: Path,
) -> None:
    source = tmp_path / "Campaigns.w3v"
    payload = cache_bytes(((), (), (), (), (("name", b"saved\0"),)))
    source.write_bytes(payload)
    report = analyze_real_save_path(source, text_encoding="utf-16-le")
    assert report.complete and report.files[0].kind is SaveFileKind.GAMECACHE
    assert report.files[0].text_decoding is None and report.files[0].raw_text is None
    assert source.read_bytes() == payload


def test_invalid_encoding_is_rejected_before_accessing_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import gametool.real_save_files as save_files

    def forbid(_path):
        pytest.fail("invalid encoding must be rejected before source access")

    monkeypatch.setattr(save_files, "_candidate_files", forbid)
    with pytest.raises(ValueError, match="编码"):
        analyze_real_save_path(tmp_path, text_encoding="latin-1")
    with pytest.raises(SystemExit) as error:
        run_save_code_cli(("--text", "-load ABCD1234", "--encoding", "utf-16-le"))
    assert error.value.code == 2
