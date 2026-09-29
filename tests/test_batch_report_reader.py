"""Batch report reader header evolution (legacy trailing-column variants)."""

from __future__ import annotations

import pytest

from w3xtool.batch_report_reader import (
    BatchReportValidationError,
    read_report_rows_bytes,
)
from w3xtool.batch_tsv import format_tsv_rows
from w3xtool.item_relation_exports import (
    ACQUISITION_REPORT_HEADER,
    ACQUISITION_REPORT_LEGACY_HEADERS,
)


def _tsb(header: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    return format_tsv_rows((header, *rows)).encode("utf-8")


def test_exact_header_rows_pass_through_unchanged() -> None:
    # Given: a report written with the current schema.
    content = _tsb(
        ACQUISITION_REPORT_HEADER, (("a",) * len(ACQUISITION_REPORT_HEADER),)
    )

    # When: it is read against the same header.
    rows = read_report_rows_bytes(
        content, "掉落与获取关系.tsv", ACQUISITION_REPORT_HEADER
    )

    # Then: nothing is padded or altered.
    assert rows == (("a",) * len(ACQUISITION_REPORT_HEADER),)


def test_legacy_header_rows_are_right_padded_to_current_schema() -> None:
    # Given: a report published before the trailing bilingual columns existed.
    legacy = ACQUISITION_REPORT_LEGACY_HEADERS[0]
    assert legacy == ACQUISITION_REPORT_HEADER[:-2]
    content = _tsb(legacy, (("a",) * len(legacy),))

    # When: it is read with the legacy variant declared.
    rows = read_report_rows_bytes(
        content,
        "掉落与获取关系.tsv",
        ACQUISITION_REPORT_HEADER,
        ACQUISITION_REPORT_LEGACY_HEADERS,
    )

    # Then: rows align to the current schema with empty trailing cells.
    assert len(rows[0]) == len(ACQUISITION_REPORT_HEADER)
    assert rows[0][: len(legacy)] == ("a",) * len(legacy)
    assert rows[0][len(legacy) :] == ("", "")


def test_unknown_header_still_rejected() -> None:
    # Given: a header that is neither current nor a declared legacy variant.
    content = _tsb(("列一", "列二"), (("x", "y"),))

    # When/Then: the reader refuses it exactly as before.
    with pytest.raises(BatchReportValidationError):
        read_report_rows_bytes(
            content,
            "掉落与获取关系.tsv",
            ACQUISITION_REPORT_HEADER,
            ACQUISITION_REPORT_LEGACY_HEADERS,
        )


def test_longer_legacy_variant_rejected() -> None:
    # Given: a "legacy" variant longer than the current header is illegal.
    longer = ACQUISITION_REPORT_HEADER + ("多出的列",)
    content = _tsb(longer, (("a",) * len(longer),))

    # When/Then: only shorter trailing-column variants are accepted.
    with pytest.raises(BatchReportValidationError):
        read_report_rows_bytes(
            content, "掉落与获取关系.tsv", ACQUISITION_REPORT_HEADER, (longer,)
        )


def test_malformed_legacy_row_rejected() -> None:
    # Given: a legacy-header report with a short data row.
    legacy = ACQUISITION_REPORT_LEGACY_HEADERS[0]
    content = _tsb(legacy, (("a",) * (len(legacy) - 1),))

    # When/Then: row-length validation still applies before padding.
    with pytest.raises(BatchReportValidationError):
        read_report_rows_bytes(
            content,
            "掉落与获取关系.tsv",
            ACQUISITION_REPORT_HEADER,
            ACQUISITION_REPORT_LEGACY_HEADERS,
        )
