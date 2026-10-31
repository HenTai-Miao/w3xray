"""Prove the authored acceptance rejects incomplete or misattributed evidence."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import asdict
import json
from pathlib import Path

import pytest

from gametool.api import export_all_files
from gametool.gui_offline_acceptance_mpq import (
    archive_fixture_payloads,
    validate_archive_export,
)
from gametool.gui_offline_acceptance_v12 import (
    LEGACY_EXPORT_NAMES,
    V12_CASE_NAMES,
    V12_EXPORT_NAMES,
    expected_export_names,
)
from gametool.gui_offline_acceptance_v12_evidence import (
    validate_call_evidence,
    validate_loadout_evidence,
)
from gametool.gui_offline_acceptance_v12_fixtures import (
    CALL_SOURCES,
    source_adoption_fixture_payloads,
)
from gametool.loadout_report import read_loadout_report, select_loadout_report
from gametool.script_behavior_index import build_script_behavior_index
from gametool.script_sources import AnalysisScriptSource


def test_gui_export_inventory_keeps_all_content_analysis_files() -> None:
    assert len(LEGACY_EXPORT_NAMES) == len(set(LEGACY_EXPORT_NAMES)) == 20
    assert len(V12_EXPORT_NAMES) == len(set(V12_EXPORT_NAMES)) == 8
    assert len(V12_CASE_NAMES) == len(set(V12_CASE_NAMES)) == 3
    assert len(expected_export_names()) == 29
    assert set(LEGACY_EXPORT_NAMES) < expected_export_names()


@pytest.mark.parametrize(
    "tamper", ("missing", "extra", "offset", "argument", "binding", "source", "else")
)
def test_call_acceptance_rejects_incomplete_or_invented_source_evidence(
    tamper: str,
) -> None:
    index = build_script_behavior_index(
        AnalysisScriptSource(name, text, name.endswith(".lua"))
        for name, text in CALL_SOURCES.items()
    )
    rows = [asdict(call) for call in index.calls]
    validate_call_evidence(rows)
    if tamper == "missing":
        rows.pop()
    elif tamper == "extra":
        rows.append(deepcopy(rows[0]))
    elif tamper == "offset":
        rows[0]["offset"] += 1
    elif tamper == "argument":
        rows[0]["arguments"] = rows[0]["arguments"][:-1]
    elif tamper == "binding":
        next(row for row in rows if row["callee"] == "MysteryAction")["binding"] = (
            "standard-global"
        )
    elif tamper == "source":
        rows[0]["source_fingerprint"] = "0" * 64
    else:
        next(row for row in rows if row["callee"] == "MysteryAction")["controls"] = ()
    with pytest.raises(RuntimeError):
        validate_call_evidence(rows)


@pytest.mark.parametrize(
    "tamper", ("record", "slot", "quantity", "bytes", "span", "selection")
)
def test_loadout_acceptance_rejects_dropped_raw_or_selected_evidence(
    tmp_path: Path, tamper: str
) -> None:
    raw = source_adoption_fixture_payloads()["v12/plans/nine.json"]
    path = tmp_path / "nine.json"
    path.write_bytes(raw)
    value = json.loads(
        json.dumps(select_loadout_report(read_loadout_report(path), "远征甲").to_dict())
    )
    validate_loadout_evidence(value, raw, "nine", selected=(1,))
    document = value["document"]
    if tamper == "record":
        document["records"].pop()
    elif tamper == "slot":
        document["records"][0]["slots"] = document["records"][0]["slots"][:-1]
    elif tamper == "quantity":
        document["records"][0]["slots"][0]["charge_literal"] = "9"
    elif tamper == "bytes":
        document["raw_base64"] = ""
    elif tamper == "span":
        document["nodes"][0]["byte_end"] -= 1
    else:
        value["selection"]["ordinals"] = [2]
    with pytest.raises(RuntimeError):
        validate_loadout_evidence(value, raw, "nine", selected=(1,))


@pytest.mark.parametrize(
    "tamper",
    ("hint_count", "candidate_only", "game_version", "source_inputs", "missing"),
)
def test_archive_acceptance_rejects_unproved_resource_catalog_claims(
    tmp_path: Path, tamper: str
) -> None:
    source = tmp_path / "source.w3x"
    source.write_bytes(archive_fixture_payloads()["archive-recovery.w3x"])
    output = tmp_path / "export"
    export_all_files(str(source), str(output))
    validate_archive_export(output)
    path = output / "RecoveredNames/name-hint-catalog.json"
    value = json.loads(path.read_text("utf-8"))
    if tamper == "hint_count":
        value["hint_count"] = 1190
    elif tamper == "candidate_only":
        value["candidate_only"] = False
    elif tamper == "game_version":
        value["game_version"] = "invented-build"
    elif tamper == "source_inputs":
        value["source_declared_inputs"].pop()
    else:
        path.unlink()
    if tamper != "missing":
        path.write_text(json.dumps(value, ensure_ascii=False), "utf-8")
    with pytest.raises(RuntimeError):
        validate_archive_export(output)
