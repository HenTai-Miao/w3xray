"""Follow-up regressions from the second Task 7 review."""

from __future__ import annotations

from contextlib import nullcontext
from unittest.mock import patch

from tests.test_script_sources import _MemoryArchive, _classic_wct
from w3xtool.api import MapData, commands_from_map, scan_commands
from w3xtool.load_context import MapLoadContext
from w3xtool.map_loader import _load_map_impl
from w3xtool.script_string_index import build_script_string_index
from w3xtool.wts import map_wts_table


def test_map_loading_isolates_malformed_source_object_reference_state() -> None:
    # Given: malformed JASS precedes valid object references in Lua and WCT.
    archive = _MemoryArchive({
        "war3map.j": b'call BJDebugMsg("unterminated\n',
        "war3map.lua": b'CreateItem(FourCC("I001"), 0, 0)\nInitNeutralBuildings()\n',
        "war3map.wct": _classic_wct(
            "call UnitAddAbility(null, 'A001')\ncall ChooseRandomItemBJ(1)"
        ),
    })

    # When: the normal map loader analyzes every readable source.
    md = _load_map_impl(archive, "memory.w3x", 0, None, MapLoadContext())

    # Then: unterminated quote state cannot hide later source references/features.
    assert {"I001", "A001"} <= set(md.obj_index)
    assert md.script_features == ["中立建筑(商店/酒馆等)", "随机物品"]


def test_script_string_index_prefers_retained_byte_parsed_wts() -> None:
    # Given: published WTS text differs from the authoritative retained table.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": 'call BJDebugMsg("TRIGSTR_001")',
            "war3map.wts": "STRING 1\n{\npublished wrong\n}\n",
        },
        ui_strings={1: "retained correct"},
    )

    # When: the public script string index resolves TRIGSTR literals.
    index = build_script_string_index(md)

    # Then: publication encoding cannot replace the retained byte-parsed value.
    entry = next(item for item in index.entries if item.value == "TRIGSTR_001")
    assert entry.resolved == "retained correct"


def test_scan_commands_parses_original_mixed_encoding_wts_bytes() -> None:
    # Given: per-entry WTS parsing can decode entry 1, while whole-file decoding
    # falls back because entry 2 uses another encoding.
    raw_wts = "STRING 1\n{\n保留提示\n}\nSTRING 2\n{\n".encode()
    raw_wts += "测试".encode("gbk") + "\n}\n".encode()
    archive = _MemoryArchive({
        "war3map.j": "\n".join((
            'call TriggerRegisterPlayerChatEvent(gg_trg_X, Player(0), "-x", true)',
            "function Trig_X_Actions takes nothing returns nothing",
            '    call BJDebugMsg("TRIGSTR_001")',
            "endfunction",
        )).encode(),
        "war3map.wts": raw_wts,
    })

    # When: the standalone path API collects and scans the archive.
    with patch("w3xtool.api.MPQArchive", return_value=nullcontext(archive)):
        commands = scan_commands("memory.w3x")

    # Then: the hint comes from raw per-entry WTS parsing, without mojibake.
    assert [(item.command, item.hint) for item in commands] == [("-x", "保留提示")]


def test_map_wts_table_returns_empty_for_missing_legacy_text() -> None:
    # Given / When / Then: a source-less legacy model can omit WTS entirely.
    assert map_wts_table(MapData("x.w3x", "x")) == {}


def test_map_wts_table_rejects_oversized_legacy_string_id() -> None:
    # Given: the published fallback contains an integer identifier beyond the
    # interpreter's bounded conversion limit.
    malformed = "STRING " + "9" * 5000 + "\n{\nvalue\n}\n"
    md = MapData("x.w3x", "x", scripts={"war3map.wts": malformed})

    # When / Then: malformed compatibility input degrades to no string table.
    assert map_wts_table(md) == {}


def test_commands_from_map_survives_malformed_legacy_wts() -> None:
    # Given: a valid command uses a TRIGSTR hint beside malformed fallback WTS.
    malformed = "STRING " + "9" * 5000 + "\n{\nvalue\n}\n"
    md = MapData(
        "x.w3x",
        "x",
        scripts={
            "war3map.j": "\n".join((
                'call TriggerRegisterPlayerChatEvent(gg_trg_X, Player(0), "-x", true)',
                "function Trig_X_Actions takes nothing returns nothing",
                '    call BJDebugMsg("TRIGSTR_001")',
                "endfunction",
            )),
            "war3map.wts": malformed,
        },
    )

    # When / Then: command extraction remains available with an unresolved hint.
    assert [(item.command, item.hint) for item in commands_from_map(md)] == [
        ("-x", "TRIGSTR_001"),
    ]
