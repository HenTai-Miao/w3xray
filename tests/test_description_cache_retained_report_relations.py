"""Exact metric and problem-path relations for retained report rows."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tests.retained_integrity_fixture import active_cache, install_previous, retained
from tests.windows_cache_contract_fixture import report_fixture
from gametool import description_cache_retained_integrity as retained_api
from gametool.windows_output_paths import native_output_path


type JsonValue = (
    str | int | float | bool | list["JsonValue"] | dict[str, "JsonValue"] | None
)


def _payload(tmp_path: Path, row_kind: str) -> dict[str, JsonValue]:
    active = active_cache(tmp_path)
    paths: tuple[Path, ...] = ()
    unsafe_previous: Path | None = None
    unsafe_sibling: Path | None = None
    if row_kind == "valid":
        paths = (install_previous(active, tmp_path),)
    elif row_kind == "invalid-inventory":
        previous = install_previous(active, tmp_path)
        (previous / "来源清单.tsv").unlink()
        paths = (previous,)
    elif row_kind == "invalid-exact-inventory":
        previous = install_previous(active, tmp_path)
        (previous / "来源清单.tsv").unlink()
        previous_io = Path(native_output_path(str(previous)))
        (previous_io / "forged-extra.tsv").write_bytes(b"forged")
        paths = (previous,)
    elif row_kind == "invalid-nested":
        previous = install_previous(active, tmp_path)
        # The parser consumes an explicit unsafe proof, not a POSIX link scan.
        unsafe_previous = previous
    elif row_kind == "regular":
        artifact = retained(active, "2", "failed-output")
        artifact.write_bytes(b"evidence")
        paths = (artifact,)
    else:
        unsafe_sibling = retained(active, "2", "recovery")
    report = report_fixture(
        active, paths, unsafe_previous=unsafe_previous, unsafe_sibling=unsafe_sibling
    )
    payload: JsonValue = json.loads(
        retained_api.format_description_cache_retention_report(report)
    )
    assert isinstance(payload, dict)
    return payload


@pytest.mark.parametrize(
    ("row_kind", "updates"),
    (
        ("valid", {"file_count": 4}),
        ("valid", {"entry_count": 4}),
        ("valid", {"problem_path": "leaf"}),
        ("regular", {"file_count": 2}),
        ("regular", {"entry_count": 1}),
        ("regular", {"problem_path": "leaf"}),
        ("unsafe", {"size": 0}),
        ("unsafe", {"problem_path": "leaf"}),
    ),
)
def test_report_parser_rejects_impossible_metric_relations(
    tmp_path: Path,
    row_kind: str,
    updates: dict[str, JsonValue],
) -> None:
    payload = _payload(tmp_path, row_kind)
    retained_rows = payload["retained"]
    assert isinstance(retained_rows, list)
    row = retained_rows[0]
    assert isinstance(row, dict)
    row.update(updates)

    with pytest.raises(ValueError):
        retained_api.parse_description_cache_retention_report(json.dumps(payload))


@pytest.mark.parametrize(
    ("row_kind", "updates"),
    (
        ("invalid-inventory", {"problem_path": None}),
        (
            "invalid-nested",
            {
                "size": 0,
                "file_count": 0,
                "entry_count": 0,
                "sha256": "0" * 64,
            },
        ),
    ),
)
def test_invalid_previous_rows_reject_incomplete_problem_relations(
    tmp_path: Path,
    row_kind: str,
    updates: dict[str, JsonValue],
) -> None:
    payload = _payload(tmp_path, row_kind)
    retained_rows = payload["retained"]
    assert isinstance(retained_rows, list)
    row = retained_rows[0]
    assert isinstance(row, dict)
    row.update(updates)

    with pytest.raises(ValueError):
        retained_api.parse_description_cache_retention_report(json.dumps(payload))


def test_exact_inventory_mismatch_rejects_a_forged_non_owned_problem_path(
    tmp_path: Path,
) -> None:
    payload = _payload(tmp_path, "invalid-exact-inventory")
    retained_rows = payload["retained"]
    assert isinstance(retained_rows, list)
    row = retained_rows[0]
    assert isinstance(row, dict)
    assert row["file_count"] == 5
    assert row["entry_count"] == 5
    assert row["problem_path"] == "来源清单.tsv"
    row["problem_path"] = "forged-extra.tsv"

    with pytest.raises(ValueError):
        retained_api.parse_description_cache_retention_report(json.dumps(payload))
