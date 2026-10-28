"""Core retained-cache classification and report-codec contracts."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.windows_cache_contract_fixture import report_fixture
from tests.retained_integrity_fixture import (
    active_cache,
    backup,
    retained,
    stage,
)
from gametool import description_cache_retained_integrity as snapshot_api
from gametool.windows_output_paths import native_output_path


def test_transient_and_malformed_reasons_are_closed(tmp_path: Path) -> None:
    format_report = getattr(snapshot_api, "format_description_cache_retention_report")
    parse_report = getattr(snapshot_api, "parse_description_cache_retention_report")
    active = active_cache(tmp_path)
    stage(active, "2").mkdir()
    backup(active, "3").write_bytes(b"backup")
    (active.parent / ".gamexray-description-cache-stage-bad").mkdir()
    (active.parent / ".gamexray-description-cache-backup-bad").mkdir()
    (active.parent / ".gamexray-description-cache-retained-bad").mkdir()

    report = report_fixture(active, include_publication_names=True)

    assert {item.reason.value for item in report.transient} == {
        "stage-transient",
        "backup-transient",
    }
    assert {item.reason.value for item in report.malformed} == {
        "malformed-stage-name",
        "malformed-backup-name",
        "malformed-retained-name",
    }
    payload = json.loads(format_report(report))
    payload["malformed"][0]["reason"] = "unknown"
    with pytest.raises(ValueError):
        parse_report(json.dumps(payload))


def test_report_codec_rejects_unsorted_rows_and_unsafe_problem_paths(
    tmp_path: Path,
) -> None:
    format_report = getattr(snapshot_api, "format_description_cache_retention_report")
    parse_report = getattr(snapshot_api, "parse_description_cache_retention_report")
    active = active_cache(tmp_path)
    for digit in ("3", "2"):
        path = retained(active, digit, "failed-output")
        path_io = Path(native_output_path(str(path)))
        path_io.mkdir()
        (path_io / "leaf").write_bytes(digit.encode())
    report = report_fixture(
        active, tuple(retained(active, digit, "failed-output") for digit in ("3", "2"))
    )
    payload = json.loads(format_report(report))
    payload["retained"].reverse()
    with pytest.raises(ValueError):
        parse_report(json.dumps(payload))
    payload["retained"].reverse()
    payload["retained"][0]["problem_path"] = "../escape"
    with pytest.raises(ValueError):
        parse_report(json.dumps(payload))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "new-kind"),
        ("validation", "new-validation"),
        ("sha256", None),
        ("sha256", "A" * 64),
        ("extra", "unexpected"),
    ],
)
def test_report_codec_rejects_unknown_fields_and_inconsistent_proofs(
    tmp_path: Path,
    field: str,
    value: str | None,
) -> None:
    active = active_cache(tmp_path)
    artifact = retained(active, "2", "failed-output")
    artifact.write_bytes(b"evidence")
    report = report_fixture(active, (artifact,))
    payload = json.loads(snapshot_api.format_description_cache_retention_report(report))
    payload["retained"][0][field] = value

    with pytest.raises(ValueError):
        snapshot_api.parse_description_cache_retention_report(json.dumps(payload))
