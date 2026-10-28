"""WTS evidence reaches real map loading without selecting conflicting names."""

from __future__ import annotations

import struct
import sys

import pytest

from gametool.api import _script_only_map
from gametool.load_context import MapLoadContext
from gametool.map_loader import _load_map_impl
from gametool.script_string_index import build_script_string_index
from gametool.wts_models import WtsRecordState
from gametool.object_candidate_values import wts_value_source
from tests.test_object_pipeline import FakeArchive, _binary_object
from tests.test_script_sources import _MemoryArchive


def _strings() -> bytes:
    return (
        b"STRING 1\n{\nwrong first\n}\n"
        b"STRING 1\n{\nwrong last\n}\n"
        b"STRING 2\nmissing opening\n"
        b"STRING 3\n{\nconfirmed tooltip\n}\n"
    )


def test_real_object_name_and_fields_keep_unresolved_references_beside_valid_values() -> (
    None
):
    archive = FakeArchive(
        {
            "war3map.wts": _strings(),
            "war3map.w3u": _binary_object(
                "hfoo",
                "H001",
                (
                    ("unam", "TRIGSTR_1"),
                    ("utip", "TRIGSTR_3"),
                    ("utub", "TRIGSTR_2"),
                ),
            ),
        }
    )
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())
    obj = md.obj_identity_index[("单位", "H001")]

    assert obj.name == "TRIGSTR_1"
    assert obj.field_values["display:name"] == "TRIGSTR_1"
    assert obj.field_values["utip"] == "confirmed tooltip"
    assert obj.field_values["utub"] == "TRIGSTR_2"
    assert md.ui_strings == {3: "confirmed tooltip"}
    assert md.wts_reports["war3map.wts"].raw_bytes == _strings()
    assert any(
        row.component == "wts" and "conflicting WTS values" in row.message
        for row in md.diagnostics
    )
    assert any(
        row.component == "wts" and "incomplete WTS block" in row.message
        for row in md.diagnostics
    )


def test_map_and_campaign_domains_keep_independent_ids_and_metadata_resolution() -> (
    None
):
    campaign_wts = b"STRING 1\n{\ncampaign title\n}\n"
    # The retained W3F header is enough to prove which string domain supplied it.
    campaign_header = struct.pack("<iii", 1, 1, 1) + b"TRIGSTR_1\x00\x00\x00\x00"
    archive = FakeArchive(
        {
            "war3map.wts": _strings(),
            "war3campaign.wts": campaign_wts,
            "war3map.w3u": _binary_object("hfoo", "H001", (("unam", "TRIGSTR_1"),)),
            "war3campaign.w3u": _binary_object(
                "hfoo", "H002", (("unam", "TRIGSTR_1"),)
            ),
            "war3campaign.w3f": campaign_header,
        }
    )
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    assert md.obj_index["H001"].name == "TRIGSTR_1"
    assert md.obj_index["H002"].name == "campaign title"
    assert md.w3f is not None and md.w3f.name == "campaign title"
    assert md.wts_reports["war3campaign.wts"].complete
    assert md.wts_reports["war3campaign.wts"].table == {1: "campaign title"}
    assert md.wts_reports["war3map.wts"].table == {3: "confirmed tooltip"}
    assert not any(
        row.component == "wts" and row.source == "war3campaign.wts"
        for row in md.diagnostics
    )


def test_script_only_loading_exposes_partial_evidence_and_preserves_script_offsets() -> (
    None
):
    script = b'call BJDebugMsg("TRIGSTR_1")\r\ncall BJDebugMsg("TRIGSTR_3")\r\n'
    archive = _MemoryArchive({"war3map.wts": _strings(), "war3map.j": script})
    md = _script_only_map(archive, archive.path)
    index = build_script_string_index(md)

    assert md.scripts["war3map.j"].encode() == script
    assert md.ui_strings == {3: "confirmed tooltip"}
    assert md.wts_reports["war3map.wts"].records[0].state == WtsRecordState.CONFLICT
    assert [(row.value, row.resolved) for row in index.entries] == [
        ("TRIGSTR_1", ""),
        ("TRIGSTR_3", "confirmed tooltip"),
    ]
    assert archive.read_counts["war3map.wts"] == 1
    assert any(row.component == "wts" for row in md.diagnostics)


def test_truncated_tail_keeps_valid_table_in_both_loading_paths() -> None:
    raw = b"STRING 1\n{\nusable\n}\nSTRING 2\n{\nunfinished"
    for load in (
        lambda archive: _load_map_impl(
            archive, archive.path, 0, None, MapLoadContext()
        ),
        lambda archive: _script_only_map(archive, archive.path),
    ):
        md = load(_MemoryArchive({"war3map.wts": raw}))
        assert md.ui_strings == {1: "usable"}
        report = md.wts_reports["war3map.wts"]
        assert report.records[1].raw_bytes.endswith(b"unfinished")
        assert not report.complete
        assert any(
            row.component == "wts" and row.source == "war3map.wts"
            for row in md.diagnostics
        )


@pytest.mark.parametrize(
    "leading_zeros", [False, True], ids=["large-id", "leading-zeros"]
)
def test_binary_object_loading_and_source_provenance_keep_complete_long_wts_ids(
    leading_zeros: bool,
) -> None:
    digits = "0" * 5000 + "1" if leading_zeros else "9" * 5000
    canonical = "1" if leading_zeros else digits
    sid = 1 if leading_zeros else 10**5000 - 1
    quota = sys.get_int_max_str_digits()
    raw = ("STRING " + digits + "\n{\nresolved complete name\n}\n").encode()
    archive = FakeArchive(
        {
            "war3map.wts": raw,
            "war3map.w3u": _binary_object(
                "hfoo", "H001", (("unam", "TRIGSTR_" + digits),)
            ),
        }
    )

    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())
    obj = md.obj_identity_index[("单位", "H001")]
    evidence = next(
        row
        for row in obj.field_evidence
        if row.key == "unam" and row.source == "war3map.w3u"
    )

    assert obj.name == obj.field_values["display:name"] == "resolved complete name"
    assert md.ui_strings == {sid: "resolved complete name"}
    assert evidence.value_source == "war3map.wts#STRING " + canonical
    assert md.wts_reports["war3map.wts"].raw_bytes == raw
    assert md.wts_reports["war3map.wts"].records[0].id_text == digits
    assert not any(row.component == "wts" for row in md.diagnostics)
    assert wts_value_source("TRIGSTR_" + digits, {}, "war3map") == ""
    assert sys.get_int_max_str_digits() == quota


def test_comment_continuations_resolve_real_object_names_in_normal_loading() -> None:
    raw = b"STRING 1\n// first comment line\nsecond comment line\n{\ncorrect title\n}\n"
    archive = FakeArchive(
        {
            "war3map.wts": raw,
            "war3map.w3u": _binary_object("hfoo", "H001", (("unam", "TRIGSTR_1"),)),
        }
    )
    md = _load_map_impl(archive, archive.path, 0, None, MapLoadContext())

    assert md.obj_index["H001"].name == "correct title"
    assert md.ui_strings == {1: "correct title"}
    assert md.wts_reports["war3map.wts"].complete
    assert md.wts_reports["war3map.wts"].raw_bytes == raw
    assert not any(row.component == "wts" for row in md.diagnostics)
