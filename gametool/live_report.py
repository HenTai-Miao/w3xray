"""Versioned live-report persistence and identity-aware offline comparison.

This module never opens a game process.  A saved capture is historical evidence;
its original timestamp, unknown states and every extension field are retained.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
import os
from pathlib import Path
from typing import Any

from .live_report_io import (
    read_report_bytes,
    validate_report_destination,
    verify_report_source,
    write_report_bytes,
)
from .live_report_json import (
    ExactJsonNumber,
    LiveReportError,
    format_report_json,
    json_compatible,
    parse_report_json,
)

__all__ = [
    "ExactJsonNumber",
    "LiveReport",
    "LiveReportDiff",
    "LiveReportError",
    "compare_live_reports",
    "format_live_report_diff",
    "read_live_report",
    "validate_report_destination",
    "write_live_report",
]

REPORT_SCHEMA = "gamexray-live-report"
REPORT_SCHEMA_VERSION = 1
DIFF_SCHEMA = "gamexray-live-report-diff"

_LIST_FIELDS = frozenset(
    {
        "selected_units",
        "units",
        "owned_units",
        "all_units",
        "unit_matches",
        "slots",
        "resources",
        "evidence",
    }
)
_LIVE_KEYS = _LIST_FIELDS | frozenset(
    {"selected_unit", "strategy_used", "selection_complete", "process_identity"}
)


class LiveReport(dict[str, Any]):
    """Raw report mapping with separate file/schema provenance.

    ``to_json()`` emits the full raw report with exact numeric JSON tokens.
    ``to_dict()`` is compatible with ordinary JSON encoders; exact fractions use
    ``{"value_type":"exact-json-number","value":"..."}`` transport values.
    """

    def __init__(
        self,
        report: Mapping[str, Any],
        *,
        metadata: Mapping[str, Any] | None = None,
        source: Mapping[str, Any] | None = None,
        original_bytes: bytes | None = None,
    ) -> None:
        super().__init__(report)
        self.metadata = dict(metadata or {})
        self.source = dict(source or {})
        self.original_bytes = original_bytes

    def to_json(self) -> str:
        return format_report_json(self)

    def to_dict(self) -> dict[str, Any]:
        return json_compatible(self)


class LiveReportDiff(dict[str, Any]):
    """Complete structured comparison, with exact JSON and portable transports."""

    def to_json(self) -> str:
        return format_report_json(self)

    def to_dict(self) -> dict[str, Any]:
        return json_compatible(self)


def _validate_report(report: Any) -> dict[str, Any]:
    if not isinstance(report, dict):
        raise LiveReportError("A live report must be one JSON object")
    if not _LIVE_KEYS.intersection(report):
        raise LiveReportError(
            "JSON object is not an unambiguous live report (missing live evidence keys)"
        )
    pid = report.get("pid")
    if pid is not None and (
        not isinstance(pid, int) or isinstance(pid, bool) or pid < 1
    ):
        raise LiveReportError("Live report pid must be a positive integer or null")
    unit_rows: list[dict[str, Any]] = []
    for key in _LIST_FIELDS:
        value = report.get(key)
        if value is not None and not isinstance(value, list):
            raise LiveReportError(f"Live report {key!r} must be an array or null")
        if isinstance(value, list):
            for ordinal, row in enumerate(value):
                if not isinstance(row, dict):
                    raise LiveReportError(
                        f"Live report {key}[{ordinal}] must be an object"
                    )
                if key in {
                    "selected_units",
                    "units",
                    "owned_units",
                    "all_units",
                    "unit_matches",
                }:
                    unit_rows.append(row)
    selected = report.get("selected_unit")
    if selected is not None and not isinstance(selected, dict):
        raise LiveReportError("Live report selected_unit must be an object or null")
    if isinstance(selected, dict):
        unit_rows.append(selected)
    for row in unit_rows:
        if "items" in row and row["items"] is not None:
            if not isinstance(row["items"], list) or any(
                not isinstance(item, dict) for item in row["items"]
            ):
                raise LiveReportError(
                    "Unit inventory items must be an object array or null"
                )
        for key in ("items_complete", "inventory_complete", "evidence_complete"):
            if key in row and row[key] is not None and not isinstance(row[key], bool):
                raise LiveReportError(
                    f"Unit completeness field {key!r} must be a boolean or null"
                )
    for key in ("notes", "selection_diagnostics"):
        if (
            key in report
            and report[key] is not None
            and not isinstance(report[key], list)
        ):
            raise LiveReportError(f"Live report {key!r} must be an array or null")
    for key in report:
        if (
            key.endswith("_complete")
            and report[key] is not None
            and not isinstance(report[key], bool)
        ):
            raise LiveReportError(
                f"Completeness field {key!r} must be a boolean or null"
            )
    return report


def _capture_metadata(report: Mapping[str, Any]) -> dict[str, Any]:
    names = {
        "pid",
        "version",
        "captured_at",
        "process_identity",
        "map_identity",
        "map_epoch",
        "game_session_id",
        "strategy_used",
        "selection_complete",
        "selection_diagnostics",
        "notes",
    }
    return {
        key: value
        for key, value in report.items()
        if key in names or key.endswith("_complete")
    }


def write_live_report(path: str | os.PathLike[str], report: Mapping[str, Any]) -> Path:
    """Save every report field in a schema-1 document at a fresh destination."""
    # Canonicalize supported in-memory JSON types without mutating the caller.
    payload = _validate_report(parse_report_json(format_report_json(report)))
    provenance: dict[str, Any] = {"capture": _capture_metadata(payload)}
    if isinstance(report, LiveReport):
        provenance["imported_source"] = report.source
        provenance["imported_document"] = report.metadata
    document = {
        "schema": REPORT_SCHEMA,
        "schema_version": REPORT_SCHEMA_VERSION,
        "saved_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "provenance": provenance,
        "report": payload,
    }
    encoded = (format_report_json(document) + "\n").encode("utf-8", errors="strict")
    return write_report_bytes(path, encoded)


def read_live_report(path: str | os.PathLike[str]) -> LiveReport:
    """Read a stable schema-1 report or unambiguous legacy plain live JSON."""
    original, source = read_report_bytes(path)
    try:
        text = original.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise LiveReportError(f"Report is not strict UTF-8: {exc}") from exc
    document = parse_report_json(text)
    if not isinstance(document, dict):
        raise LiveReportError("A report document must be one JSON object")
    if "schema" in document:
        if document["schema"] != REPORT_SCHEMA:
            raise LiveReportError(
                "Unsupported live report schema: "
                + format_report_json(document["schema"])
            )
        if (
            type(document.get("schema_version")) is not int
            or document["schema_version"] != REPORT_SCHEMA_VERSION
        ):
            raise LiveReportError(
                "Unsupported live report schema_version: "
                + format_report_json(document.get("schema_version"))
            )
        payload = _validate_report(document.get("report"))
        metadata = {key: value for key, value in document.items() if key != "report"}
    else:
        payload = _validate_report(document)
        metadata = {
            "schema": "legacy-live-json",
            "schema_version": None,
            "diagnostics": [
                "Legacy plain live JSON; capture completeness and identity are retained only when explicitly recorded."
            ],
        }
    verify_report_source(source)
    return LiveReport(
        payload, metadata=metadata, source=source, original_bytes=original
    )


def compare_live_reports(
    old: Mapping[str, Any], new: Mapping[str, Any]
) -> LiveReportDiff:
    """Compare all observations, proving instance/absence claims independently."""
    from .live_report_diff import compare_report_values

    old_value = _validate_report(parse_report_json(format_report_json(old)))
    new_value = _validate_report(parse_report_json(format_report_json(new)))
    return LiveReportDiff(compare_report_values(old_value, new_value, old=old, new=new))


def format_live_report_diff(result: Mapping[str, Any]) -> str:
    """Render full changes and diagnostics; retain unchanged evidence in JSON."""
    lines = [
        "实时报告离线比较（历史读数）",
        "比较完整性: "
        + (
            "完整"
            if result.get("comparison_complete") is True
            else "不完整 / 身份或覆盖范围不确定"
        ),
        "记录变化: "
        + ("有" if result.get("has_changes") is True else "未发现已记录值变化"),
    ]
    identity = result.get("identity", {})
    lines.append("身份依据: " + format_report_json(identity))
    for side in ("old", "new"):
        lines.append(
            ("旧报告" if side == "old" else "新报告")
            + ": "
            + format_report_json(result.get(side))
        )
    diagnostics = result.get("diagnostics", [])
    if isinstance(diagnostics, list):
        for diagnostic in diagnostics:
            lines.append("诊断: " + format_report_json(diagnostic))
    changes = result.get("changes", [])
    if isinstance(changes, list):
        lines.append(f"完整变化记录 ({len(changes)}):")
        for change in changes:
            lines.append(format_report_json(change))
    lines.append("缺失、不可用和未读取保持为未知；只比较报告明确记录的证据。")
    return "\n".join(lines)
