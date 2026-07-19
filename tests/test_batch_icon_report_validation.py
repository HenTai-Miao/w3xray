"""Strict publication validation for structured unresolved-icon reports."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Final, TypedDict

import pytest

from tests.batch_icon_report_fixture import (
    validate_icon_publication,
    validate_missing_gap_publication,
)
from w3xtool.icon_evidence_models import IconGapReason


class _ReferencePayload(TypedDict):
    category: str
    rawcode: str
    base: str
    name: str
    field: str
    label: str
    type: str
    source: str
    wts: str
    map: str
    scope: str


_VALID_REFERENCE = _ReferencePayload(
    category="技能",
    rawcode="A001",
    base="AHbz",
    name="暴风雪",
    field="aart",
    label="图标 - 普通",
    type="icon",
    source="war3map.w3a",
    wts="",
    map="map.w3x",
    scope="map.w3x",
)
_INVALID_REFERENCE_JSON: Final = (
    ("malformed", "{"),
    ("empty", "[]"),
    ("missing", json.dumps(({"category": "技能"},), ensure_ascii=False)),
    (
        "extra",
        json.dumps(({**_VALID_REFERENCE, "extra": "value"},), ensure_ascii=False),
    ),
    (
        "duplicate",
        json.dumps((_VALID_REFERENCE, _VALID_REFERENCE), ensure_ascii=False),
    ),
)


def test_publication_validation_accepts_one_reconciled_gap_row(
    tmp_path: Path,
) -> None:
    # Given / When
    validation = validate_icon_publication(tmp_path)

    # Then
    assert validation.valid


def test_publication_validation_accepts_empty_path_for_invalid_reference(
    tmp_path: Path,
) -> None:
    # Given / When: an eligible icon field is explicitly empty, so no normalized
    # path can exist but the evidence still belongs in the structured gap report.
    validation = validate_icon_publication(
        tmp_path,
        requested_path="",
        normalized_path="",
        reason=IconGapReason.INVALID_REFERENCE,
    )

    # Then: the knowledge gap must not turn a valid map publication into failure.
    assert validation.valid


@pytest.mark.parametrize(("_case", "reference_json"), _INVALID_REFERENCE_JSON)
def test_publication_validation_rejects_invalid_reference_identities(
    tmp_path: Path,
    _case: str,
    reference_json: str,
) -> None:
    # Given / When
    validation = validate_icon_publication(
        tmp_path,
        reference_json=reference_json,
    )

    # Then
    assert not validation.valid
    assert validation.code == "report_schema_mismatch"


def test_publication_validation_rejects_duplicate_map_path_gap_rows(
    tmp_path: Path,
) -> None:
    # Given / When
    validation = validate_icon_publication(tmp_path, duplicate_gap_row=True)

    # Then
    assert not validation.valid
    assert validation.code == "report_schema_mismatch"


def test_publication_validation_rejects_resolved_and_gap_path_conflict(
    tmp_path: Path,
) -> None:
    # Given / When
    validation = validate_icon_publication(tmp_path, resolved_conflict=True)

    # Then
    assert not validation.valid
    assert validation.code == "report_schema_mismatch"
    assert "conflict" in validation.detail


def test_publication_validation_allows_same_path_in_distinct_submaps(
    tmp_path: Path,
) -> None:
    # Given / When
    validation = validate_icon_publication(tmp_path, resolved_other_map=True)

    # Then
    assert validation.valid


@pytest.mark.parametrize(
    "diagnostics_json",
    (
        "{",
        '["client_not_provided", "client_not_provided"]',
        '["historical_evidence_checked", "client_not_provided"]',
        '["unknown"]',
    ),
)
def test_publication_validation_rejects_invalid_icon_diagnostics(
    tmp_path: Path,
    diagnostics_json: str,
) -> None:
    # Given / When: the required report has malformed, duplicate, unordered, or unknown flags.
    validation = validate_icon_publication(
        tmp_path,
        diagnostics_json=diagnostics_json,
    )

    # Then: reuse never accepts non-canonical diagnostic evidence.
    assert not validation.valid
    assert validation.code == "report_schema_mismatch"


def test_publication_validation_requires_the_unresolved_icon_report(
    tmp_path: Path,
) -> None:
    # Given / When
    validation = validate_missing_gap_publication(tmp_path)

    # Then
    assert not validation.valid
    assert validation.code == "required_report_missing"
