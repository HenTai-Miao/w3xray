"""Full offline observation comparison with explicit identity/coverage boundaries."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import re
from typing import Any

from .live_report_json import (
    integer_from_text,
    scalar_identity,
    values_equal,
)
from .object_codes import valid_object_code

_MISSING = object()
_UNIT_COLLECTIONS = frozenset(
    {"selected_units", "units", "owned_units", "all_units", "unit_matches"}
)
_IDENTITY_FIELDS = frozenset(
    {
        "pid",
        "captured_at",
        "version",
        "process_identity",
        "map_identity",
        "map_epoch",
        "game_session_id",
    }
)
_UNKNOWN_STATES = frozenset(
    {
        "unknown",
        "unavailable",
        "invalid",
        "conflict",
        "declared-layout-only",
        "declared_layout_only",
        "unsupported",
    }
)
_ADDRESS = re.compile(r"(?:0[xX][0-9a-fA-F]+|[0-9]+)")
type _Pending = tuple[str, Any, Any, Mapping[str, Any], Mapping[str, Any], bool]


def _pointer(path: str, key: str | int) -> str:
    text = str(key).replace("~", "~0").replace("/", "~1")
    return path + "/" + text


def _semantic_role(path: str) -> str | None:
    """Bind collection meaning to report structure, not extension field names."""
    parts = path.split("/")[1:]
    if len(parts) == 1 and parts[0] in _UNIT_COLLECTIONS | {
        "slots",
        "resources",
        "evidence",
    }:
        return parts[0]
    if len(parts) == 3 and parts[1].isdecimal():
        if parts[0] in _UNIT_COLLECTIONS and parts[2] in {"items", "evidence"}:
            return parts[2]
        if parts[0] == "slots" and parts[2] == "evidence":
            return "evidence"
    if (
        len(parts) == 5
        and parts[0] in _UNIT_COLLECTIONS
        and parts[1].isdecimal()
        and parts[2] == "items"
        and parts[3].isdecimal()
        and parts[4] == "evidence"
    ):
        return "evidence"
    return None


def _record_scope(path: str) -> str | None:
    parts = path.split("/")[1:]
    if len(parts) == 2 and parts[1].isdecimal():
        if parts[0] in _UNIT_COLLECTIONS:
            return "unit"
        if parts[0] in {"slots", "resources"}:
            return "item" if parts[0] == "slots" else "resource"
    if (
        len(parts) == 4
        and parts[0] in _UNIT_COLLECTIONS
        and parts[1].isdecimal()
        and parts[2] == "items"
        and parts[3].isdecimal()
    ):
        return "item"
    return None


def _known(value: Any) -> bool:
    return value is not None and value is not _MISSING


def _uncertain_state(value: Any) -> bool:
    if not isinstance(value, Mapping) or "state" not in value:
        return False
    state = value["state"]
    return (
        not isinstance(state, str)
        or state in _UNKNOWN_STATES
        or ("complete" in value and value["complete"] is not True)
    )


def _report_identity(report: Mapping[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in report.items() if key in _IDENTITY_FIELDS}


def _marker_relation(
    old: Mapping[str, Any], new: Mapping[str, Any], keys: tuple[str, ...]
) -> bool | None:
    common = [
        key
        for key in keys
        if _known(old.get(key))
        and _known(new.get(key))
        and old[key] != ""
        and new[key] != ""
        and not _uncertain_state(old[key])
        and not _uncertain_state(new[key])
    ]
    if not common:
        return None
    return all(values_equal(old[key], new[key]) for key in common)


def _process(report: Mapping[str, Any]) -> tuple[dict[str, Any], list[str]]:
    value = report.get("process_identity")
    process = dict(value) if isinstance(value, Mapping) else {}
    diagnostics: list[str] = []
    pid = report.get("pid", process.get("pid"))
    if (
        _known(process.get("pid"))
        and _known(pid)
        and not values_equal(pid, process["pid"])
    ):
        diagnostics.append("Top-level PID conflicts with opened-process identity PID")
    process["pid"] = pid
    for first, verified in (
        ("creation_time", "verified_creation_time"),
        ("executable_path", "verified_executable_path"),
    ):
        if (
            _known(process.get(first))
            and _known(process.get(verified))
            and not values_equal(process[first], process[verified])
        ):
            diagnostics.append(f"Opened-process {first} differs from its verification")
    if isinstance(process.get("state"), str) and process["state"] in _UNKNOWN_STATES:
        diagnostics.append("Opened-process identity is explicitly unconfirmed")
    return process, diagnostics


def _map_markers(report: Mapping[str, Any]) -> dict[str, Any]:
    result = {
        key: report[key] for key in ("map_epoch", "game_session_id") if key in report
    }
    nested = report.get("map_identity")
    if isinstance(nested, Mapping):
        result.update(
            {
                "map_identity." + key: nested[key]
                for key in ("epoch", "session_id", "game_session_id")
                if key in nested
            }
        )
    return result


def _build(report: Mapping[str, Any]) -> Mapping[str, Any]:
    version = report.get("version")
    if isinstance(version, Mapping):
        return {
            key: version[key]
            for key in (
                "version",
                "engine",
                "arch",
                "architecture",
                "build",
                "fingerprint",
            )
            if key in version
        }
    return {"version": version} if isinstance(version, str) else {}


def _identity(old: Mapping[str, Any], new: Mapping[str, Any]) -> dict[str, Any]:
    left, left_errors = _process(old)
    right, right_errors = _process(new)
    diagnostics = ["Old report: " + error for error in left_errors] + [
        "New report: " + error for error in right_errors
    ]
    pid_relation = _marker_relation(left, right, ("pid",))
    path_relation = _marker_relation(
        left, right, ("executable_path", "exe_path", "opened_exe_path")
    )
    process_relation = _marker_relation(
        left,
        right,
        (
            "creation_time",
            "process_start_time",
            "start_time",
            "process_instance_id",
            "session_id",
        ),
    )
    time_format_relation = _marker_relation(left, right, ("creation_time_format",))
    if time_format_relation is False:
        process_relation = False
    elif ("creation_time_format" in left) != ("creation_time_format" in right):
        process_relation = None
    if pid_relation is False or path_relation is False:
        process_relation = False
    elif pid_relation is None or left_errors or right_errors:
        process_relation = None
    old_build, new_build = _build(old), _build(new)
    build_relation = _marker_relation(
        old_build,
        new_build,
        ("version", "engine", "arch", "architecture", "build", "fingerprint"),
    )
    if (
        build_relation is True
        and _marker_relation(old_build, new_build, ("version", "build", "fingerprint"))
        is None
    ):
        build_relation = None
    map_relation = _marker_relation(
        _map_markers(old),
        _map_markers(new),
        (
            "map_epoch",
            "game_session_id",
            "map_identity.epoch",
            "map_identity.session_id",
            "map_identity.game_session_id",
        ),
    )
    old_map, new_map = old.get("map_identity"), new.get("map_identity")
    if isinstance(old_map, Mapping) and isinstance(new_map, Mapping):
        fingerprint_relation = _marker_relation(
            old_map, new_map, ("sha256", "fingerprint", "source_identity")
        )
        if fingerprint_relation is False:
            map_relation = False
    if process_relation is None:
        diagnostics.append(
            "Process instance is unproved: PID/executable path alone cannot exclude PID reuse."
        )
    elif process_relation is False:
        diagnostics.append(
            "Reports belong to different process instances or conflicting process identities."
        )
    if build_relation is None:
        diagnostics.append("A common game build/architecture was not recorded.")
    elif build_relation is False:
        diagnostics.append("Game build/architecture differs between reports.")
    if map_relation is None:
        diagnostics.append(
            "Same-match map epoch is unknown; the same map file does not prove the same match."
        )
    elif map_relation is False:
        diagnostics.append("Map/match identity differs between reports.")
    relations = (process_relation, build_relation, map_relation)
    state = (
        "incompatible"
        if False in relations
        else "confirmed"
        if all(value is True for value in relations)
        else "uncertain"
    )
    return {
        "state": state,
        "same_process": process_relation,
        "same_build": build_relation,
        "same_map_epoch": map_relation,
        "diagnostics": diagnostics,
        "old": _report_identity(old),
        "new": _report_identity(new),
    }


def _address(value: Any) -> tuple[Any, ...] | None:
    if isinstance(value, int) and not isinstance(value, bool) and value > 0:
        return ("address", scalar_identity(value))
    if isinstance(value, str) and _ADDRESS.fullmatch(value):
        number = (
            int(value, 16)
            if value.lower().startswith("0x")
            else integer_from_text(value)
        )
        if number > 0:
            return ("address", scalar_identity(number))
    return None


def _field_known(row: Mapping[str, Any], key: str) -> bool:
    """Qualify an actual record field using its own declared typed evidence.

    Legacy raw fields remain usable when no field evidence was declared. An
    explicit unknown/conflicting mirror overrides raw presence; extension
    dictionaries are never searched for evidence or identity-looking words.
    """
    value = row.get(key, _MISSING)
    if not _known(value) or _uncertain_state(row):
        return False
    evidence = row.get("evidence", _MISSING)
    if evidence is _MISSING:
        return True
    if not isinstance(evidence, list):
        return False
    aliases = {"addr", "address"} if key in {"addr", "address"} else {key}
    matching = [
        entry
        for entry in evidence
        if isinstance(entry, Mapping)
        and isinstance(entry.get("key"), str)
        and entry["key"] in aliases
    ]
    if not matching:
        return True
    if len(matching) != 1:
        return False
    entry = matching[0]
    if (
        entry.get("state") != "confirmed"
        or _uncertain_state(entry)
        or not _known(entry.get("value", _MISSING))
    ):
        return False
    if key in {"addr", "address"}:
        return _address(value) is not None and _address(value) == _address(
            entry["value"]
        )
    return values_equal(value, entry["value"])


def _physical(row: Mapping[str, Any]) -> tuple[Any, ...] | None:
    for name in ("instance_id", "handle_id", "handle"):
        value = row.get(name)
        if _known(value):
            if not _field_known(row, name):
                return None
            if not (
                (isinstance(value, str) and bool(value))
                or (
                    isinstance(value, int) and not isinstance(value, bool) and value > 0
                )
            ):
                return None
            generation = row.get("generation")
            if generation is not None and not _field_known(row, "generation"):
                return None
            if generation is not None and not (
                (isinstance(generation, str) and bool(generation))
                or (
                    isinstance(generation, int)
                    and not isinstance(generation, bool)
                    and generation >= 0
                )
            ):
                return None
            return (
                name,
                scalar_identity(value),
                scalar_identity(row.get("generation")),
            )
    key = "addr" if "addr" in row else "address"
    return _address(row.get(key)) if _field_known(row, key) else None


def _record_key(row: Any, role: str) -> tuple[Any, ...] | None:
    if not isinstance(row, Mapping):
        return None
    if role == "items" or role == "slots":
        slot = row.get("slot")
        if (
            isinstance(slot, int)
            and not isinstance(slot, bool)
            and slot >= 0
            and _field_known(row, "slot")
        ):
            return ("slot", slot)
        return None
    if role == "evidence":
        key = row.get("key")
        return ("key", key) if isinstance(key, str) and key else None
    if role == "resources":
        physical = _physical(row)
        if physical is not None:
            return physical
        for key in ("owner", "player", "slot", "player_index"):
            value = row.get(key)
            if _field_known(row, key) and (
                (isinstance(value, str) and bool(value))
                or (
                    isinstance(value, int)
                    and not isinstance(value, bool)
                    and value >= 0
                )
            ):
                return (key, scalar_identity(value))
        return None
    return _physical(row)


def _item_identity_known(row: Mapping[str, Any]) -> bool:
    code = row.get("code")
    return (
        _physical(row) is not None
        and _field_known(row, "code")
        and _field_known(row, "slot")
        and isinstance(code, str)
        and valid_object_code(code)
    )


def _coverage(report: Mapping[str, Any], role: str, context: Mapping[str, Any]) -> bool:
    if role == "selected_units":
        return report.get("selection_complete") is True
    if role == "slots" and "slots_complete" in report:
        return report["slots_complete"] is True
    if role in {"items", "slots"}:
        declared = [
            context[key]
            for key in ("items_complete", "inventory_complete")
            if key in context
        ]
        return bool(declared) and all(value is True for value in declared)
    if role == "evidence":
        return context.get("evidence_complete") is True
    return report.get(role + "_complete") is True


def _context_identity(old: Mapping[str, Any], new: Mapping[str, Any]) -> Any:
    fields = (
        "instance_id",
        "handle",
        "handle_id",
        "generation",
        "addr",
        "address",
        "code",
        "unit",
        "owner",
        "slot",
        "key",
    )
    left = {name: old[name] for name in fields if name in old}
    right = {name: new[name] for name in fields if name in new}
    return {"old": left, "new": right} if left or right else None


@dataclass(slots=True)
class _Comparison:
    old: Mapping[str, Any]
    new: Mapping[str, Any]
    identity: dict[str, Any]
    changes: list[dict[str, Any]] = field(default_factory=list)
    diagnostics: list[dict[str, Any]] = field(default_factory=list)
    complete: bool = True

    def diagnose(self, path: str, kind: str, message: str, **details: Any) -> None:
        self.complete = False
        self.diagnostics.append(
            {"path": path, "kind": kind, "message": message, **details}
        )

    def change(
        self,
        path: str,
        kind: str,
        old: Any,
        new: Any,
        *,
        state: str = "observed",
        identity: Any = None,
    ) -> None:
        self.changes.append(
            {
                "path": path,
                "kind": kind,
                "state": state,
                "old_present": old is not _MISSING,
                "new_present": new is not _MISSING,
                "old": None if old is _MISSING else old,
                "new": None if new is _MISSING else new,
                "identity": identity,
            }
        )

    def collection(
        self,
        path: str,
        role: str,
        old: list[Any],
        new: list[Any],
        old_context: Mapping[str, Any],
        new_context: Mapping[str, Any],
        uncertain: bool = False,
    ) -> list[_Pending]:
        old_complete = _coverage(self.old, role, old_context)
        new_complete = _coverage(self.new, role, new_context)
        if not old_complete or not new_complete:
            self.diagnose(
                path,
                "coverage_unknown",
                "Collection coverage is not explicitly complete; missing records do not prove absence.",
                old_complete=old_complete,
                new_complete=new_complete,
            )
        indexes: list[dict[tuple[Any, ...], list[tuple[int, Any]]]] = []
        unkeyed: list[list[tuple[int, Any]]] = []
        for side, rows in (("old", old), ("new", new)):
            indexed: dict[tuple[Any, ...], list[tuple[int, Any]]] = {}
            unknown: list[tuple[int, Any]] = []
            for ordinal, row in enumerate(rows):
                if _uncertain_state(row):
                    self.diagnose(
                        _pointer(path, ordinal),
                        "unconfirmed_evidence",
                        f"{side} collection record has an unconfirmed declared state.",
                        side=side,
                        record=row,
                    )
                key = _record_key(row, role)
                if key is None:
                    unknown.append((ordinal, row))
                    self.diagnose(
                        _pointer(path, ordinal),
                        "physical_identity_missing",
                        f"{side} record has no unambiguous physical identity/slot; no rawcode/name matching was attempted.",
                        side=side,
                        record=row,
                    )
                else:
                    indexed.setdefault(key, []).append((ordinal, row))
            for entries in indexed.values():
                if len(entries) > 1:
                    self.diagnose(
                        path,
                        "duplicate_physical_identity",
                        f"{side} collection repeats a physical identity; every record is retained without selecting the first.",
                        side=side,
                        records=[row for _, row in entries],
                        ordinals=[ordinal for ordinal, _ in entries],
                    )
            indexes.append(indexed)
            unkeyed.append(unknown)
        old_index, new_index = indexes
        keys = dict.fromkeys([*old_index, *new_index])
        pending: list[_Pending] = []

        def retain_raw(
            left: list[tuple[int, Any]], right: list[tuple[int, Any]]
        ) -> None:
            # This compares encoded records, with uncertainty carried into all
            # descendants. It never pairs unknown physical instances by name.
            for index in range(max(len(left), len(right))):
                if index < len(left):
                    old_ordinal, old_row = left[index]
                else:
                    old_ordinal, old_row = right[index][0], _MISSING
                new_ordinal, new_row = (
                    right[index] if index < len(right) else (old_ordinal, _MISSING)
                )
                pending.append(
                    (
                        _pointer(
                            path, old_ordinal if index < len(left) else new_ordinal
                        ),
                        old_row,
                        new_row,
                        old_row if isinstance(old_row, Mapping) else old_context,
                        new_row if isinstance(new_row, Mapping) else new_context,
                        True,
                    )
                )

        same_session = self.identity["state"] == "confirmed"
        for key in keys:
            left, right = old_index.get(key, []), new_index.get(key, [])
            if len(left) > 1 or len(right) > 1:
                retain_raw(left, right)
                continue
            if (
                len(left) == len(right) == 1
                and self.identity["state"] != "incompatible"
            ):
                old_ordinal, old_row = left[0]
                new_ordinal, new_row = right[0]
                row_path = _pointer(path, old_ordinal)
                if role in {"items", "slots"}:
                    item_changed = _physical(old_row) != _physical(
                        new_row
                    ) or not values_equal(old_row.get("code"), new_row.get("code"))
                    if (
                        item_changed
                        and _item_identity_known(old_row)
                        and _item_identity_known(new_row)
                    ):
                        item_uncertain = (
                            uncertain
                            or _uncertain_state(old_row)
                            or _uncertain_state(new_row)
                        )
                        confirmed = (
                            same_session
                            and old_complete
                            and new_complete
                            and not item_uncertain
                        )
                        self.change(
                            row_path,
                            "item_replaced"
                            if confirmed
                            else "inventory_observation_changed",
                            old_row,
                            new_row,
                            state="uncertain"
                            if item_uncertain
                            else "confirmed"
                            if confirmed
                            else "observed",
                            identity={
                                "slot": old_row.get("slot"),
                                "old_ordinal": old_ordinal,
                                "new_ordinal": new_ordinal,
                            },
                        )
                # Every record still traverses the ordinary comparison path;
                # summaries cannot hide nested unknown evidence or fields.
                pending.append(
                    (row_path, old_row, new_row, old_row, new_row, uncertain)
                )
                continue
            can_confirm = (
                same_session
                and not uncertain
                and old_complete
                and new_complete
                and len(left) <= 1
                and len(right) <= 1
                and not any(_uncertain_state(row) for _, row in [*left, *right])
                and (
                    role not in {"items", "slots"}
                    or all(_item_identity_known(row) for _, row in [*left, *right])
                )
            )
            for ordinal, row in left:
                self.change(
                    _pointer(path, ordinal),
                    "record_removed" if can_confirm else "observed_only_old",
                    row,
                    _MISSING,
                    state="confirmed" if can_confirm else "uncertain",
                    identity={"side": "old", "ordinal": ordinal, "role": role},
                )
            for ordinal, row in right:
                self.change(
                    _pointer(path, ordinal),
                    "record_added" if can_confirm else "observed_only_new",
                    _MISSING,
                    row,
                    state="confirmed" if can_confirm else "uncertain",
                    identity={"side": "new", "ordinal": ordinal, "role": role},
                )
        retain_raw(unkeyed[0], unkeyed[1])
        return pending

    def compare(self, old: Any, new: Any) -> None:
        pending: list[_Pending] = [("", old, new, self.old, self.new, False)]
        while pending:
            path, left, right, old_context, new_context, uncertain = pending.pop()
            uncertain = uncertain or _uncertain_state(left) or _uncertain_state(right)
            role = _semantic_role(path)
            parent_path, _, field = path.rpartition("/")
            if (
                _record_scope(parent_path) is not None
                and not isinstance(left, Mapping | list)
                and not isinstance(right, Mapping | list)
            ):
                field_known = _field_known(old_context, field) and _field_known(
                    new_context, field
                )
                if (
                    not field_known
                    and left is not _MISSING
                    and right is not _MISSING
                    and left is not None
                    and right is not None
                ):
                    self.diagnose(
                        path,
                        "unconfirmed_evidence",
                        "Declared typed evidence does not confirm the raw record field.",
                        field=field,
                        old_evidence=old_context.get("evidence"),
                        new_evidence=new_context.get("evidence"),
                    )
                uncertain = uncertain or not field_known
            context_identity = _context_identity(old_context, new_context)
            if left is _MISSING or right is _MISSING:
                if left is _MISSING and right is _MISSING:
                    continue
                self.change(
                    path,
                    "field_missing",
                    left,
                    right,
                    state="uncertain",
                    identity=context_identity,
                )
                self.diagnose(
                    path,
                    "field_missing",
                    "An omitted field is unknown, not an observed zero/empty/absence.",
                )
                continue
            if left is None or right is None:
                if left is not right:
                    self.change(
                        path,
                        "availability_changed",
                        left,
                        right,
                        state="uncertain",
                        identity=context_identity,
                    )
                self.diagnose(
                    path,
                    "unavailable",
                    "Null evidence is unavailable; it does not confirm empty contents.",
                )
                continue
            if isinstance(left, Mapping) and isinstance(right, Mapping):
                for side, value in (("old", left), ("new", right)):
                    if "state" in value and not isinstance(value["state"], str):
                        self.diagnose(
                            path,
                            "invalid_evidence_state",
                            f"{side} evidence state is not a declared string.",
                            side=side,
                            record=value,
                        )
                    if _uncertain_state(value):
                        self.diagnose(
                            path,
                            "unconfirmed_evidence",
                            f"{side} evidence has an explicit unconfirmed state.",
                            side=side,
                            record=value,
                        )
                keys = dict.fromkeys([*left, *right])
                for key in reversed(keys):
                    pending.append(
                        (
                            _pointer(path, key),
                            left.get(key, _MISSING),
                            right.get(key, _MISSING),
                            left,
                            right,
                            uncertain,
                        )
                    )
                continue
            if isinstance(left, list) and isinstance(right, list):
                if role in _UNIT_COLLECTIONS | {
                    "items",
                    "slots",
                    "resources",
                    "evidence",
                }:
                    pending.extend(
                        reversed(
                            self.collection(
                                path,
                                role,
                                left,
                                right,
                                old_context,
                                new_context,
                                uncertain,
                            )
                        )
                    )
                else:
                    # Unknown extension arrays and notes remain ordered evidence.
                    for index in range(max(len(left), len(right)) - 1, -1, -1):
                        pending.append(
                            (
                                _pointer(path, index),
                                left[index] if index < len(left) else _MISSING,
                                right[index] if index < len(right) else _MISSING,
                                old_context,
                                new_context,
                                uncertain,
                            )
                        )
                continue
            if not values_equal(left, right):
                self.change(
                    path,
                    "value_changed",
                    left,
                    right,
                    state="uncertain"
                    if uncertain
                    else "confirmed"
                    if self.identity["state"] == "confirmed"
                    else "observed",
                    identity=context_identity,
                )


def _selection(report: Mapping[str, Any], comparison: _Comparison, side: str) -> Any:
    units = report.get("selected_units", _MISSING)
    legacy = report.get("selected_unit", _MISSING)
    if units is None:
        comparison.diagnose(
            "/selected_units",
            "selection_unavailable",
            f"{side} selected_units is explicitly unavailable; legacy evidence cannot prove a complete empty selection.",
            side=side,
            **({"selected_unit": legacy} if legacy is not _MISSING else {}),
        )
        return None
    if isinstance(units, list):
        if isinstance(legacy, Mapping) and (
            not units or not values_equal(legacy, units[0])
        ):
            comparison.diagnose(
                "/selected_unit",
                "legacy_selection_conflict",
                f"{side} legacy selected_unit does not mirror the first selected_units entry; both declarations are retained.",
                side=side,
                selected_unit=legacy,
                selected_units=units,
            )
        return units
    if isinstance(legacy, Mapping):
        return [legacy]
    if legacy is None and report.get("selection_complete") is True:
        return []
    return None if units is _MISSING else units


def _summary(report: Mapping[str, Any], original: Mapping[str, Any]) -> dict[str, Any]:
    summary = _report_identity(report)
    summary["selection_complete"] = report.get("selection_complete")
    summary["source"] = getattr(original, "source", None)
    summary["document"] = getattr(original, "metadata", None)
    return summary


def compare_report_values(
    old_values: dict[str, Any],
    new_values: dict[str, Any],
    *,
    old: Mapping[str, Any],
    new: Mapping[str, Any],
) -> dict[str, Any]:
    identity = _identity(old_values, new_values)
    comparison = _Comparison(
        old_values, new_values, identity, complete=identity["state"] == "confirmed"
    )
    for message in identity["diagnostics"]:
        comparison.diagnostics.append(
            {"path": "", "kind": "identity_boundary", "message": message}
        )
    left = {
        key: value
        for key, value in old_values.items()
        if key not in {"selected_unit", "selected_units", "captured_at"}
    }
    right = {
        key: value
        for key, value in new_values.items()
        if key not in {"selected_unit", "selected_units", "captured_at"}
    }
    left["selected_units"] = _selection(old_values, comparison, "old")
    right["selected_units"] = _selection(new_values, comparison, "new")
    comparison.compare(left, right)
    # Legacy-only/conflicting declarations must remain independently comparable.
    old_legacy, new_legacy = (
        old_values.get("selected_unit", _MISSING),
        new_values.get("selected_unit", _MISSING),
    )
    if any(
        item["kind"] in {"legacy_selection_conflict", "selection_unavailable"}
        for item in comparison.diagnostics
    ):
        comparison.compare(
            {"legacy_selected_unit": old_legacy}, {"legacy_selected_unit": new_legacy}
        )
    return {
        "schema": "gamexray-live-report-diff",
        "schema_version": 1,
        "comparison_complete": comparison.complete,
        "has_changes": bool(comparison.changes),
        "input_error": False,
        "identity": identity,
        "changes": comparison.changes,
        "diagnostics": comparison.diagnostics,
        "old": _summary(old_values, old),
        "new": _summary(new_values, new),
    }
