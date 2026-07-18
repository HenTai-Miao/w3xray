"""Captured-payload-only validation contracts for retained previous caches."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Never

import pytest

from tests.retained_integrity_fixture import active_cache, install_previous
from w3xtool import description_cache_retained_integrity as retained_api
from w3xtool import description_cache_retained_tree as tree_api
from w3xtool import trusted_description_cache_validation as validation_api
from w3xtool.description_cache_retained_file_proof import RetainedFileRead
from w3xtool.integrity_cli import run_integrity_cli


def test_previous_validation_uses_only_ten_captured_leaf_reads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    active = active_cache(tmp_path)
    install_previous(active, tmp_path)
    original_read = tree_api.read_relative_retained_file
    read_count = 0

    def count_read(
        root_descriptor: int,
        expected: tree_api.TreeEntryState,
        maximum: int,
        capture_payload: bool,
    ) -> RetainedFileRead:
        nonlocal read_count
        read_count += 1
        return original_read(root_descriptor, expected, maximum, capture_payload)

    def forbid_source_root(_path: Path) -> Never:
        raise AssertionError("retained validation accessed manifest.source_root")

    monkeypatch.setattr(tree_api, "read_relative_retained_file", count_read)
    monkeypatch.setattr(validation_api, "_canonical_source_root", forbid_source_root)

    report = retained_api.inspect_retained_description_caches(active)

    assert report.retained[0].validation.value == "valid-cache"
    assert read_count == 10


@pytest.mark.parametrize("unsafe_kind", ("symlink", "special"))
def test_nested_unsafe_previous_is_an_invalid_artifact_report(
    tmp_path: Path,
    unsafe_kind: str,
) -> None:
    active = active_cache(tmp_path)
    previous = install_previous(active, tmp_path)
    unsafe = previous / "unsafe"
    if unsafe_kind == "symlink":
        unsafe.symlink_to(tmp_path / "outside")
    elif hasattr(os, "mkfifo"):
        os.mkfifo(unsafe)
    else:
        pytest.skip("POSIX FIFO fixtures are unavailable")
    output = tmp_path / f"{unsafe_kind}.json"

    code = run_integrity_cli(
        (
            "retained-cache",
            "--active-root",
            str(active),
            "--output",
            str(output),
        )
    )

    assert code == 1
    report_text = output.read_text(encoding="utf-8")
    payload = json.loads(report_text)
    assert payload["retained"][0]["validation"] == "invalid-previous"
    assert payload["retained"][0]["problem_path"] == "unsafe"
    parsed = retained_api.parse_description_cache_retention_report(report_text)
    assert parsed.retained[0].validation.value == "invalid-previous"
