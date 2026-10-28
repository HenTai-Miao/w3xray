"""File, directory and explicitly requested inline save-code evidence inputs."""

from __future__ import annotations

import hashlib
import io
import json
from pathlib import Path
import sys

import pytest

from gametool.save_code_cli import run_save_code_cli


def test_single_text_file_retains_its_name_hash_and_byte_offsets(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "profile.pld"
    raw = b'\xef\xbb\xbfPreload("-load SINGLE123")\r\n'
    source.write_bytes(raw)
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    assert run_save_code_cli((str(source), "--json")) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["scanned"] == 1 and payload["total"] == 1
    code = payload["codes"][0]
    assert code["source"] == "profile.pld"
    assert code["source_sha256"] == hashlib.sha256(raw).hexdigest()
    assert raw[code["byte_offset"] : code["byte_end"]] == code["raw"].encode()
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before


def test_log_directory_and_single_log_share_unknown_language_carriers(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "session.log"
    source.write_text('Preload("-load LOG12345")\n', encoding="utf-8")
    assert run_save_code_cli((str(tmp_path), "--json")) == 0
    directory = json.loads(capsys.readouterr().out)
    assert run_save_code_cli((str(source), "--json")) == 0
    single = json.loads(capsys.readouterr().out)
    assert directory["codes"] == single["codes"]
    assert directory["text_carriers"] == single["text_carriers"]
    assert single["codes"][0]["map_validation"] == "not_performed"


def test_inline_text_uses_the_shared_byte_level_extractor(
    capsys: pytest.CaptureFixture[str],
) -> None:
    text = 'Preload("-load PASTED123")'
    assert run_save_code_cli(("--text", text, "--json")) == 0
    value = json.loads(capsys.readouterr().out)
    code = value["codes"][0]
    assert code["source"] == "<text>" and code["encoding"] == "utf-8"
    assert code["source_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert code["code"] == "-load PASTED123"
    assert value["map_validation"] == "not_performed"


def test_only_explicit_stdin_reads_the_input_stream(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    class ForbiddenInput(io.StringIO):
        def read(self, *_args, **_kwargs):
            pytest.fail("stdin was read without explicit --stdin")

    monkeypatch.setattr(sys, "stdin", ForbiddenInput())
    with pytest.raises(SystemExit) as error:
        run_save_code_cli(("--json",))
    assert error.value.code == 2
    capsys.readouterr()
    monkeypatch.setattr(
        sys,
        "stdin",
        io.TextIOWrapper(io.BytesIO(b'Preload("-load STDIN123")'), encoding="utf-8"),
    )
    assert run_save_code_cli(("--stdin", "--json")) == 0
    value = json.loads(capsys.readouterr().out)
    assert value["codes"][0]["source"] == "<stdin>"


def test_explicit_binary_file_keeps_encoding_failure_instead_of_replacement(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    source = tmp_path / "private.sav"
    source.write_bytes(b"\0\xff\xff\0-load NOTPROVED")
    assert run_save_code_cli((str(source), "--json")) == 2
    value = json.loads(capsys.readouterr().out)
    assert value["codes"] == value["text_carriers"] == []
    assert "未识别完整文本编码" in value["diagnostics"][0]


def test_multiple_input_modes_are_rejected_before_read(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        run_save_code_cli((str(tmp_path), "--text", "-load WRONG123", "--json"))
    assert error.value.code == 2
    assert "三种来源只能选择一种" in capsys.readouterr().err


def test_missing_or_empty_source_is_a_diagnostic_result(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    for path in (tmp_path, tmp_path / "missing.txt"):
        assert run_save_code_cli((str(path), "--json")) == 2
        value = json.loads(capsys.readouterr().out)
        assert value["scanned"] == 0 and value["diagnostics"]
