"""Behavioral tests for structured extraction diagnostics."""

from __future__ import annotations


def test_record_diagnostic_deduplicates_exact_entries_in_first_seen_order() -> None:
    # Given: one map and diagnostics containing an exact duplicate.
    from w3xtool.extraction_diagnostics import (
        DiagnosticSeverity,
        ExtractionDiagnostic,
        record_diagnostic,
    )
    from w3xtool.map_data import MapData

    md = MapData("x.w3x", "Example")
    warning = ExtractionDiagnostic(
        "wts",
        "war3map.wts",
        "decode",
        DiagnosticSeverity.WARNING,
        "bad bytes",
        True,
    )
    error = ExtractionDiagnostic(
        "w3u",
        "war3map.w3u",
        "parse",
        DiagnosticSeverity.ERROR,
        "bad record",
        False,
    )

    # When: diagnostics are recorded in arrival order.
    record_diagnostic(md, warning)
    record_diagnostic(md, error)
    record_diagnostic(md, warning)

    # Then: only exact duplicates are removed without changing order.
    assert md.diagnostics == [warning, error]
