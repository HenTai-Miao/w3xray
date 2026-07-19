"""Readable script collection and per-language analysis contracts."""

from __future__ import annotations

import struct
from unittest.mock import patch

from w3xtool.api import MapData, _best_script_text, commands_from_map, recipes_from_map
from w3xtool.extraction_diagnostics import DiagnosticSeverity, ExtractionDiagnostic
from w3xtool.knowledge_script_exports import all_script_text
from w3xtool.load_context import MapLoadContext
from w3xtool.map_loader import _load_map_impl
from w3xtool.script_mechanics import scan_script_features
from w3xtool.script_sources import analysis_script_texts, collect_readable_scripts
from w3xtool.script_text_export import build_readable_script_exports
from w3xtool.wct import WctDiagnostic


class _MemoryArchive:
    path = "memory.w3x"
    _data = b""

    def __init__(self, files: dict[str, bytes]) -> None:
        self.files = dict(files)
        self.read_counts: dict[str, int] = {}

    def has_file(self, name: str) -> bool:
        return name in self.files

    def read_file(self, name: str) -> bytes:
        self.read_counts[name] = self.read_counts.get(name, 0) + 1
        return self.files[name]

    def list_files(self) -> list[str]:
        return list(self.files)

    def close(self) -> None:
        return None


def _classic_wct(custom_code: str, triggers: tuple[str, ...] = ()) -> bytes:
    data = struct.pack("<I", 1) + b"\x00"
    encoded = custom_code.encode("gbk")
    data += struct.pack("<i", len(encoded) + 1) + encoded + b"\x00"
    data += struct.pack("<i", len(triggers))
    for trigger in triggers:
        block = trigger.encode("gbk")
        data += struct.pack("<I", len(block) + 1) + block + b"\x00"
    return data


def _source_archive() -> _MemoryArchive:
    return _MemoryArchive(
        {
            "war3map.j": "// 剑圣\ncall DoNothing()\n".encode("gbk"),
            "war3map.lua": "-- 圣骑士\nDoNothing()\n".encode("gbk"),
            "war3map.wts": "STRING 1\n{\n开始游戏\n}\n".encode("gbk"),
            "war3map.wtg": b"\xffWTG-binary\x00",
            "war3map.wct": _classic_wct('call BJDebugMsg("自定义代码")'),
        }
    )


def test_collect_readable_scripts_decodes_text_and_excludes_binary_members() -> None:
    # Given: legacy-encoded JASS, Lua and WTS plus binary WTG/WCT members.
    archive = _source_archive()

    # When: readable scripts are collected.
    collection = collect_readable_scripts(archive)

    # Then: only decoded text and the non-empty virtual WCT text are published.
    assert collection.binary_members == ("war3map.wtg", "war3map.wct")
    assert set(collection.texts) == {
        "war3map.j",
        "war3map.lua",
        "war3map.wts",
        "war3map.wct(自定义代码).txt",
    }
    assert "剑圣" in collection.texts["war3map.j"]
    assert "圣骑士" in collection.texts["war3map.lua"]
    assert "开始游戏" in collection.texts["war3map.wts"]
    assert "自定义代码" in collection.texts["war3map.wct(自定义代码).txt"]


def test_collect_readable_scripts_is_repeatable_and_reads_wct_once_per_call() -> None:
    # Given: one reusable in-memory archive.
    archive = _source_archive()

    # When: collection is repeated.
    first = collect_readable_scripts(archive)
    second = collect_readable_scripts(archive)

    # Then: results are stable and raw WTG is never read as script text.
    assert first == second
    assert archive.read_counts["war3map.wct"] == 2
    assert "war3map.wtg" not in archive.read_counts


def test_collect_readable_scripts_keeps_confirmed_wct_text_with_diagnostic() -> None:
    # Given: one confirmed trigger block followed by a truncated second block.
    confirmed = "call Confirmed()".encode()
    data = struct.pack("<I", 1) + b"\x00" + struct.pack("<i", 0) + struct.pack("<i", 2)
    data += struct.pack("<I", len(confirmed) + 1) + confirmed + b"\x00"
    data += struct.pack("<I", 20) + b"partial"

    # When: the partial WCT is collected.
    collection = collect_readable_scripts(_MemoryArchive({"war3map.wct": data}))

    # Then: confirmed code is readable and truncation remains explicit.
    assert collection.wct_diagnostic is WctDiagnostic.TRUNCATED
    assert "call Confirmed()" in collection.texts["war3map.wct(自定义代码).txt"]


def test_collect_readable_scripts_does_not_publish_empty_virtual_wct() -> None:
    # Given / When: an empty but valid WCT is collected.
    collection = collect_readable_scripts(
        _MemoryArchive({"war3map.wct": _classic_wct("")})
    )

    # Then: membership remains visible without inventing an empty text export.
    assert collection.binary_members == ("war3map.wct",)
    assert collection.wct_diagnostic is None
    assert "war3map.wct(自定义代码).txt" not in collection.texts


def test_analysis_script_texts_returns_sorted_readable_analysis_sources() -> None:
    # Given: mixed readable, WTS and binary-looking entries.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {
        "war3map.lua": "lua",
        "war3map.wts": "wts",
        "notes.txt": "wct text",
        "war3map.j": "jass",
        "war3map.wtg": "raw wtg",
        "war3map.wct": "raw wct",
    }

    # When / Then: analysis keeps source names and only accepted suffixes.
    assert analysis_script_texts(md) == (
        ("notes.txt", "wct text"),
        ("war3map.j", "jass"),
        ("war3map.lua", "lua"),
    )


def test_analysis_script_texts_excludes_nul_and_whitespace_placeholders() -> None:
    # Given: protected archives may expose nominal script members without code.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {
        "war3map.j": "\x00",
        "war3map.lua": "\r\n\t ",
        "notes.txt": "call Confirmed()",
    }

    # When / Then: only substantive readable code is accepted for analysis.
    assert analysis_script_texts(md) == (("notes.txt", "call Confirmed()"),)


def test_best_script_text_keeps_legacy_primary_preference() -> None:
    # Given / When / Then: compatibility callers still receive JASS before Lua.
    scripts = {"war3map.lua": "lua", "war3map.j": "jass"}
    assert _best_script_text(scripts) == "jass"


def test_map_loading_analyzes_jass_lua_and_wct_once() -> None:
    # Given: each readable language contributes a distinct object or feature clue.
    jass = "call CreateUnit(Player(0), 'H001', 0, 0, 0)\ncall ChooseRandomItemBJ(1)\n"
    lua = 'CreateItem(FourCC("I001"), 0, 0)\nInitNeutralBuildings()\n'
    archive = _MemoryArchive(
        {
            "war3map.j": jass.encode(),
            "war3map.lua": lua.encode(),
            "war3map.wtg": b"not-a-valid-wtg",
            "war3map.wct": _classic_wct("call UnitAddAbility(null, 'A001')"),
        }
    )

    # When: the normal map loader analyzes the in-memory archive.
    md = _load_map_impl(archive, "memory.w3x", 0, None, MapLoadContext())

    # Then: binary sources stay unpublished and every readable source contributes.
    assert {"H001", "I001", "A001"} <= set(md.obj_index)
    expected_features, _codes = scan_script_features(jass + "\n" + lua)
    assert md.script_features == expected_features
    assert "war3map.wtg" not in md.scripts
    assert "war3map.wct" not in md.scripts
    assert archive.read_counts["war3map.wct"] == 1


def test_map_loading_records_partial_wct_diagnostic() -> None:
    # Given: one confirmed WCT block followed by a truncated block.
    confirmed = "call Confirmed()".encode()
    data = struct.pack("<I", 1) + b"\x00" + struct.pack("<i", 0) + struct.pack("<i", 2)
    data += struct.pack("<I", len(confirmed) + 1) + confirmed + b"\x00"
    data += struct.pack("<I", 20) + b"partial"

    # When: normal map loading publishes the readable source.
    md = _load_map_impl(
        _MemoryArchive({"war3map.wct": data}),
        "memory.w3x",
        0,
        None,
        MapLoadContext(),
    )

    # Then: confirmed text and the typed recovery status remain observable.
    assert "call Confirmed()" in md.scripts["war3map.wct(自定义代码).txt"]
    assert md.diagnostics == [
        ExtractionDiagnostic(
            component="wct",
            source="war3map.wct",
            stage="parse",
            severity=DiagnosticSeverity.WARNING,
            message="WCT parse diagnostic: truncated",
            recoverable=True,
            exception_type="WctDiagnostic",
        )
    ]


def test_map_loading_parses_wts_from_original_mixed_encoding_bytes() -> None:
    # Given: one WTS containing independently encoded UTF-8 and GBK entries.
    raw_wts = "STRING 1\n{\n开始\n}\nSTRING 2\n{\n".encode()
    raw_wts += "测试".encode("gbk") + "\n}\n".encode()
    archive = _MemoryArchive({"war3map.wts": raw_wts})
    parsed_inputs: list[bytes] = []

    def capture_wts(data: bytes) -> dict[int, str]:
        parsed_inputs.append(data)
        return {}

    # When: map loading parses strings for object metadata.
    with patch("w3xtool.map_loader.parse_wts", side_effect=capture_wts):
        _load_map_impl(archive, "memory.w3x", 0, None, MapLoadContext())

    # Then: the byte-oriented parser receives the untouched mixed stream.
    assert parsed_inputs == [raw_wts]
    assert archive.read_counts["war3map.wts"] == 1


def test_map_loading_preserves_byte_parsed_mixed_encoding_wts() -> None:
    # Given: one WTS containing independently encoded UTF-8 and GBK entries.
    raw_wts = "STRING 1\n{\n开始\n}\nSTRING 2\n{\n".encode()
    raw_wts += "测试".encode("gbk") + "\n}\n".encode()

    # When: normal loading parses map-local UI strings.
    md = _load_map_impl(
        _MemoryArchive({"war3map.wts": raw_wts}),
        "memory.w3x",
        0,
        None,
        MapLoadContext(),
    )

    # Then: downstream ECA publication can reuse both correctly decoded entries.
    assert md.ui_strings == {1: "开始", 2: "测试"}


def test_commands_from_map_scans_both_primary_languages() -> None:
    # Given: JASS and Lua register distinct chat commands.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.j": 'call TriggerRegisterPlayerChatEvent(tj, Player(0), "-jass", true)',
            "war3map.lua": 'TriggerRegisterPlayerChatEvent(tl, Player(0), "-lua", true)',
        },
    )

    # When / Then: neither language is discarded.
    assert {item.command for item in commands_from_map(md)} == {"-jass", "-lua"}


def test_recipes_from_map_scans_lua_when_jass_is_present() -> None:
    # Given: a non-empty JASS source and a recipe that exists only in Lua.
    lua = """
function LuaRecipe()
    RemoveItem(CreateItem(FourCC("I001"), 0, 0))
    RemoveItem(CreateItem(FourCC("I002"), 0, 0))
    UnitAddItemById(u, FourCC("I003"))
end
"""
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={"war3map.j": "call DoNothing()", "war3map.lua": lua},
    )

    # When / Then: the Lua result remains visible.
    recipes = recipes_from_map(md)
    assert [(item.ingredients, item.result) for item in recipes] == [
        (["I001", "I002"], "I003")
    ]


def test_exports_and_joined_scans_use_only_analysis_texts_with_source_labels() -> None:
    # Given: readable scripts plus manually injected binary entries.
    md = MapData(
        path="x.w3x",
        name="x",
        scripts={
            "war3map.lua": "lua body",
            "war3map.j": "jass body",
            "war3map.wts": "STRING 1\n{\ntext\n}",
            "war3map.wtg": "raw wtg",
            "war3map.wct": "raw wct",
            "war3map.wct(自定义代码).txt": "custom body",
        },
    )

    # When: export and joined-analysis views are built.
    export_names = {item.name for item in build_readable_script_exports(md)}
    joined = all_script_text(md)

    # Then: binaries/WTS are excluded and joined text preserves every source label.
    assert export_names == {
        "war3map.j",
        "war3map.lua",
        "war3map.wct(自定义代码).txt",
    }
    assert "war3map.j" in joined and "jass body" in joined
    assert "war3map.lua" in joined and "lua body" in joined
    assert "war3map.wct(自定义代码).txt" in joined and "custom body" in joined
    assert "war3map.wts" not in joined
    assert "raw wtg" not in joined and "raw wct" not in joined
