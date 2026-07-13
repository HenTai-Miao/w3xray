"""Deterministic JSON and TSV views of extraction evidence."""

from __future__ import annotations

import json
import re
from typing import Final

from .extraction_ledger import BlockState, ExtractionEntry, ExtractionLedger
from .presentation_safety import single_line_text, tsv_cell


_ANSI_ESCAPE_RE: Final = re.compile(r"\x1b(?:\[[0-?]*[ -/]*[@-~])?")


def format_extraction_json(ledger: ExtractionLedger) -> str:
    """Render a versioned machine-readable extraction result."""
    payload = {
        "schema_version": ledger.schema_version,
        "source_path": _safe_text(ledger.source_path),
        "source_sha256": ledger.source_sha256,
        "status": ledger.status.value,
        "counts": {
            state.value: ledger.count(state)
            for state in BlockState
        },
        "warnings": [_safe_text(warning) for warning in ledger.warnings],
        "entries": [_json_entry(entry) for entry in ledger.entries],
    }
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def format_extraction_tsv(ledger: ExtractionLedger) -> str:
    """Render one stable, spreadsheet-safe row per evidence entry."""
    rows = [
        "block_index\tinternal_path\tstate\tsource\tdeclared_size\t"
        "written_size\tsha256\tencrypted\terror_code\tdetail",
    ]
    rows.extend(_tsv_entry(entry) for entry in ledger.entries)
    return "\n".join(rows) + "\n"


def _json_entry(entry: ExtractionEntry) -> dict[str, bool | int | str | None]:
    return {
        "block_index": entry.block_index,
        "internal_path": _safe_text(entry.internal_path),
        "state": entry.state.value,
        "source": entry.source.value,
        "declared_size": entry.declared_size,
        "written_size": entry.written_size,
        "sha256": entry.sha256,
        "encrypted": entry.encrypted,
        "error_code": _safe_text(entry.error_code),
        "detail": _safe_text(entry.detail),
    }


def _tsv_entry(entry: ExtractionEntry) -> str:
    cells = (
        "" if entry.block_index is None else str(entry.block_index),
        entry.internal_path,
        entry.state.value,
        entry.source.value,
        str(entry.declared_size),
        str(entry.written_size),
        entry.sha256,
        "1" if entry.encrypted else "0",
        entry.error_code,
        entry.detail,
    )
    return "\t".join(tsv_cell(_safe_text(cell)) for cell in cells)


def _safe_text(value: str) -> str:
    return single_line_text(_ANSI_ESCAPE_RE.sub("", value))
