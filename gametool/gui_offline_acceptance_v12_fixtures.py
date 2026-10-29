"""Independently authored v0.12 sources and fixed acceptance expectations.

These synthetic carriers exercise current GameXRay readers. They are not real
game, CASC or historical-map evidence, and their scripts are never executed.
"""

from __future__ import annotations

import json
import struct

from .gui_offline_acceptance_support import _fixture_mpq


JASS_SOURCE = "\n".join(
    (
        "function InitSource takes nothing returns nothing",
        "    // call CreateItem('BAD1', 0, 0)",
        "    call CreateUnit(Player(0), 'h001', 12.5, -8.25, 90.)",
        "    if GetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD) > 0 then",
        "        call SetPlayerState(Player(0), PLAYER_STATE_RESOURCE_GOLD, 987654321)",
        "        call UnitAddAbility(udg_Target, 'A001')",
        "    else",
        """        call MysteryAction("CreateItem('BAD2', 0, 0)", 'I001')""",
        "    endif",
        "endfunction",
        "",
    )
)
LUA_SOURCE = "\n".join(
    (
        "local spawn = CreateItem",
        "function SpawnSource()",
        '''  local text = "CreateUnit(Player(9), 'BAD3', 0, 0, 0)"''',
        "  if true then",
        '    spawn(FourCC("I002"), 7, 9)',
        "  end",
        "end",
        "",
    )
)
CALL_SOURCES = {"war3map.j": JASS_SOURCE, "extra.lua": LUA_SOURCE}
# This list is authored from the source above, without invoking any scanner.
CALL_CONTRACT = (
    (
        "war3map.j",
        3,
        "CreateUnit",
        "CreateUnit",
        ("Player(0)", "'h001'", "12.5", "-8.25", "90."),
    ),
    ("war3map.j", 3, "Player", "Player", ("0",)),
    (
        "war3map.j",
        4,
        "GetPlayerState",
        "GetPlayerState",
        ("Player(0)", "PLAYER_STATE_RESOURCE_GOLD"),
    ),
    ("war3map.j", 4, "Player", "Player", ("0",)),
    (
        "war3map.j",
        5,
        "SetPlayerState",
        "SetPlayerState",
        ("Player(0)", "PLAYER_STATE_RESOURCE_GOLD", "987654321"),
    ),
    ("war3map.j", 5, "Player", "Player", ("0",)),
    ("war3map.j", 6, "UnitAddAbility", "UnitAddAbility", ("udg_Target", "'A001'")),
    ("war3map.j", 8, "MysteryAction", "", ("\"CreateItem('BAD2', 0, 0)\"", "'I001'")),
    ("extra.lua", 5, "spawn", "CreateItem", ('FourCC("I002")', "7", "9")),
    ("extra.lua", 5, "FourCC", "FourCC", ('"I002"',)),
)
SIX_CODES = ("I001", " i2 ", "éA,;", "I001", "I005", "I006")
HUGE_QUANTITY = "9" * 4401
PLAN_NOTE = '独立来源证据\r\n第二行\t"完整"'
MAP_NAME = "霜月继承物品"
MAP_DESCRIPTION = "第一行\r\n第二行含 TAB\t与 😀"
CAMPAIGN_NAME = "北境远征 😀"
CHAPTER_NAME = "第一章 雪原"
CHAPTER_TITLE = "完整章节名称"
CHILD_MEMBER = "章节\\TRIGSTR_77.w3x"
WTS_TEXT = (
    "STRING 1\r\n{\r\n" + MAP_NAME + "\r\n}\r\n"
    "STRING 2\r\n{\r\n" + MAP_DESCRIPTION + "\r\n}\r\n"
)
CAMPAIGN_WTS_TEXT = (
    "STRING 10\r\n{\r\n" + CAMPAIGN_NAME + "\r\n}\r\n"
    "STRING 11\r\n{\r\n" + CHAPTER_NAME + "\r\n}\r\n"
    "STRING 12\r\n{\r\n" + CHAPTER_TITLE + "\r\n}\r\n"
    "STRING 77\r\n{\r\n不应成为成员路径\r\n}\r\n"
)
NAME_HINT_CATALOG_CONTRACT = {
    "schema_version": 1,
    "catalog_id": "trainer-mpq-resource-hints-v1",
    "candidate_only": True,
    "game_version": None,
    "hint_count": 1191,
    "ordered_names_sha256": "c942485e2d8a8c1cc5d5c2c87cb6d5a92525728c513fdd0f090cc85844142303",
    "source_repository": "war3-reforged-trainer",
    "source_commit": "39ddabe2dc16ca7c3be9911c41dc22c83d1b9c4d",
    "source_file": "war3_mpq_names.py",
    "source_file_sha256": "adeaf732c55c11929dc8e5e59d69f4a699e89f80e529faf3a7e27a1357ab1ac9",
    "source_document": "docs/MPQ_MEMBER_RECOVERY.md",
    "source_document_sha256": "b323153c565e9af139552dfe74d8483b3323298687683c22b9c51184b1a968ec",
    "source_declared_inputs": [
        {
            "name": "Terrain.slk",
            "sha256": "12919abf88a6016659cbd870fa8cd9b8a1ea0626a73f2015786721009da06d07",
        },
        {
            "name": "CliffTypes.slk",
            "sha256": "0b4d3870494f317f9f0a04533e4f2f9b87b580a6394ef0458f98584d723202bb",
        },
        {
            "name": "UI/war3skins.txt",
            "sha256": "f3c613ae88fc02ab607ff3b07af937e2570c0656e4b184bdd1a186255bb60956",
        },
        {
            "name": "CASC 文件路径清单",
            "sha256": "27a4fa17c981f14934ffd41f7f820128b72b5d9e33991d5aada3aa13db4e3f7d",
        },
    ],
    "confirmation": "MPQ hash probe-chain membership and exact entry read",
}


def authored_call_rows() -> list[dict[str, object]]:
    """Locate fixed literal expectations using only authored source lines."""
    rows = []
    for source, line, callee, canonical, arguments in CALL_CONTRACT:
        text = CALL_SOURCES[source]
        lines = text.splitlines(keepends=True)
        raw = callee + "(" + ", ".join(arguments) + ")"
        offset = sum(len(part) for part in lines[: line - 1]) + lines[line - 1].index(
            raw
        )
        rows.append(
            {
                "source": source,
                "language": "Lua" if source.endswith(".lua") else "JASS",
                "line": line,
                "offset": offset,
                "end_offset": offset + len(raw),
                "owner": "SpawnSource" if source.endswith(".lua") else "InitSource",
                "callee": callee,
                "canonical": canonical,
                "arguments": list(arguments),
                "raw": raw,
            }
        )
    return rows


def _json_bytes(value: object) -> bytes:
    return (json.dumps(value, ensure_ascii=False, separators=(",", ":")) + "\n").encode(
        "utf-8"
    )


def _nine_record(name: str, unit: bytes, code: bytes) -> dict[str, object]:
    return {
        "name": name,
        "unit_type_id": int.from_bytes(unit, "big"),
        "equipment": [[0, 0]] + [[int.from_bytes(code, "big"), 5]] * 8,
        "equipment_charges": list(range(9)),
        "requires_any_slot": False,
        "extension": {"note": PLAN_NOTE},
    }


def _object_records(
    records: tuple[tuple[bytes, bytes, tuple[tuple[bytes, str | int], ...]], ...],
) -> bytes:
    result = [struct.pack("<iii", 2, 0, len(records))]
    for base, code, fields in records:
        result.append(base + code + struct.pack("<i", len(fields)))
        for field, value in fields:
            if isinstance(value, str):
                result.append(
                    field + struct.pack("<i", 3) + value.encode("utf-8") + b"\0" * 5
                )
            else:
                result.append(field + struct.pack("<ii", 0, value) + b"\0" * 4)
    return b"".join(result)


def authored_w3f() -> bytes:
    """Fixed v3 layout: five added fog floats, one int, then v2 background."""

    def strings(*values: str) -> bytes:
        return b"".join(value.encode("utf-8") + b"\0" for value in values)

    return b"".join(
        (
            struct.pack("<iii", 3, 12, 6061),
            strings("TRIGSTR_10", "困难", "作者甲", "完整战役描述"),
            struct.pack("<ii", 3, 7),
            strings("UI\\背景.mdx", "UI\\小图.blp"),
            struct.pack("<i", 2),
            strings("Sound\\风声.wav"),
            struct.pack("<ifff", 1, 64.0, 1024.0, 0.25),
            bytes((1, 2, 3, 255)),
            struct.pack("<i", 4),
            struct.pack("<fffffii", 16.0, 256.0, 32.0, 512.0, 0.75, 1, 9),
            struct.pack("<ii", 1, 1),
            strings("TRIGSTR_11", "TRIGSTR_12", CHILD_MEMBER),
            struct.pack("<i", 1),
            strings("reserved-retained", CHILD_MEMBER),
        )
    )


def source_adoption_fixture_payloads() -> dict[str, bytes]:
    six = _json_bytes(
        {"schema": 1, "codes": SIX_CODES, "extension": {"note": PLAN_NOTE}}
    ).decode("utf-8")
    nine = _json_bytes(
        {
            "schema": 1,
            "records": [
                _nine_record("远征甲", b"Hpal", b"I001"),
                _nine_record("守城乙", b"Hamg", b"I002"),
            ],
        }
    ).decode("utf-8")
    nine = nine.replace(
        '"equipment_charges":[0,', '"equipment_charges":[' + HUGE_QUANTITY + ",", 1
    )
    partial = b'{"schema":1,"codes":["I001","I002","I003","I004","I005","I006"],"codes":["I007"],"extension":{"x":1,"x":2}}'
    objects = _object_records(
        (
            (b"yV11", b"yV12", ((b"igol", 7),)),
            (
                b"ratf",
                b"yV11",
                ((b"unam", "TRIGSTR_1"), (b"ides", "TRIGSTR_2"), (b"igol", 91)),
            ),
        )
    )
    standalone = _fixture_mpq(
        {
            "war3map.w3t": objects,
            "war3map.wts": b"\xff\xfe" + WTS_TEXT.encode("utf-16-le"),
            "war3map.j": JASS_SOURCE.encode("utf-8"),
        }
    )
    campaign = _fixture_mpq(
        {
            "war3campaign.w3f": authored_w3f(),
            "war3campaign.wts": b"\xfe\xff" + CAMPAIGN_WTS_TEXT.encode("utf-16-be"),
            CHILD_MEMBER: standalone,
        },
        listed=False,
    )
    payloads = {
        "v12/plans/six.json": b"\xff\xfe" + six.encode("utf-16-le"),
        "v12/plans/nine.json": nine.encode("utf-8"),
        "v12/plans/partial.json": partial,
        "v12/plans/empty.json": b'{"schema":1,"records":[]}',
        "v12/unicode-inheritance.w3x": standalone,
        "v12/unicode-campaign.w3n": campaign,
        "v12/campaign-v3.w3f": authored_w3f(),
        "v12/campaign-v3-trailing.w3f": authored_w3f() + b"\xde\xad\xbe\xef",
        "v12/calls.expected.json": _json_bytes(authored_call_rows()),
        "v12/calls-empty/脚本原始文本/war3map.j": b"// CreateUnit(Player(0), 'BAD0', 0, 0, 0)\n",
        "v12/calls-broken/脚本原始文本/war3map.j": b"function Broken takes nothing returns nothing\ncall CreateItem(\nendfunction\n",
    }
    for name, text in CALL_SOURCES.items():
        payloads[f"v12/calls-pack/脚本原始文本/{name}"] = text.encode("utf-8")
    return payloads


__all__ = ("authored_call_rows", "authored_w3f", "source_adoption_fixture_payloads")
