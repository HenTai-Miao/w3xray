"""Regression checks for strict authored GUI acceptance evidence."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.api import export_all_files, load_map
from gametool.gui_offline_acceptance_diagnostics import (
    diagnostic_fixture_payloads,
    validate_diagnostic_lines,
)
from gametool.gui_offline_acceptance_mpq import (
    archive_fixture_payloads,
    validate_archive_export,
)
from gametool.gui_reports import build_analysis_blocks


@pytest.mark.parametrize(
    "name", ["positive.j", "positive.lua", "negative.j", "negative.lua"]
)
def test_independent_diagnostic_contract_matches_loaded_authored_map(
    tmp_path: Path, name: str
) -> None:
    payloads = diagnostic_fixture_payloads()
    path = tmp_path / f"{name}.w3x"
    path.write_bytes(payloads[f"diagnostics/{name}.w3x"])
    md = load_map(str(path))
    try:
        blocks = [
            block for block in build_analysis_blocks(md) if block.title == "脚本诊断"
        ]
        assert len(blocks) == (1 if name.startswith("positive") else 0)
        validate_diagnostic_lines(name, blocks[0].lines if blocks else ())
    finally:
        md.close()


@pytest.mark.parametrize(
    "tamper", ["missing-call", "wrong-offset", "wrong-owner", "extra-group"]
)
def test_diagnostic_acceptance_rejects_incomplete_or_polluted_evidence(
    tmp_path: Path, tamper: str
) -> None:
    path = tmp_path / "positive.w3x"
    path.write_bytes(diagnostic_fixture_payloads()["diagnostics/positive.j.w3x"])
    md = load_map(str(path))
    try:
        lines = list(
            next(
                block.lines
                for block in build_analysis_blocks(md)
                if block.title == "脚本诊断"
            )
        )
    finally:
        md.close()
    if tamper == "missing-call":
        lines[1] = "\n".join(
            line for line in lines[1].splitlines() if "调用 CreateUnit" not in line
        )
    elif tamper == "wrong-offset":
        lines[1] = lines[1].replace("偏移 194:", "偏移 195:")
    elif tamper == "wrong-owner":
        lines[1] = lines[1].replace("所属函数 LocalCase", "所属函数 Independent")
    else:
        lines.append("[警告] Dz API 调用: comment-only false positive")
    with pytest.raises(RuntimeError):
        validate_diagnostic_lines("positive.j", tuple(lines))


@pytest.mark.parametrize(
    "tamper", ["none", "locale-bytes", "hash-index", "unknown-block", "extra-file"]
)
def test_archive_acceptance_checks_exact_member_and_manifest_identity(
    tmp_path: Path, tamper: str
) -> None:
    path = tmp_path / "combined.w3x"
    path.write_bytes(archive_fixture_payloads()["archive-recovery.w3x"])
    output = tmp_path / "output"
    export_all_files(str(path), str(output))
    if tamper == "none":
        validate_archive_export(output)
        return
    if tamper == "locale-bytes":
        (output / "asset.blp").write_bytes(
            (
                output
                / "RecoveredNames/blocks/block_000002-locale_0409-platform_00.blp"
            ).read_bytes()
        )
    elif tamper == "hash-index":
        manifest = output / "RecoveredNames/manifest.tsv"
        manifest.write_text(
            manifest.read_text("utf-8").replace("hash_index=25", "hash_index=26"),
            "utf-8",
        )
    elif tamper == "unknown-block":
        (output / "UnknownRaw/manifest.tsv").write_text("File000008.mpqraw\n", "utf-8")
    else:
        (output / "extra.bin").write_bytes(b"not an authored member")
    with pytest.raises(RuntimeError):
        validate_archive_export(output)
