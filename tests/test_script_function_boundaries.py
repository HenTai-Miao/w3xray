"""Lua block boundaries must not absorb adjacent function definitions."""

from __future__ import annotations

import pytest

from gametool.map_data import MapData
from gametool.script_function_index import build_script_function_index


def _ranges(text: str) -> list[tuple[str, int, int]]:
    md = MapData(path="synthetic.w3x", name="Lua boundaries")
    md.scripts = {"war3map.lua": text}
    return [
        (row.name, row.start_line, row.end_line)
        for row in build_script_function_index(md).functions
        if row.parent_offset is None
    ]


@pytest.mark.parametrize(
    "body",
    [
        "if a then\n    Work()\nelseif b then\n    Other()\nelse\n    Last()\nend",
        "if a then\n    if b then Work() elseif c then Other() end\n"
        "elseif d then\n    if e then Last() end\nend",
        "for i = 1, 3 do\n    if i > 1 then Work() end\nend",
        "for key, value in pairs(values) do Work() end",
        "while ready do\n    Work()\nend",
        "repeat\n    if ready then Work() end\nuntil done",
        "do\n    Work()\nend",
        "for i = 1, 3 do while ready do repeat Work() until done end end",
        "while (function() if a then return true else return false end end)() do\n"
        "    Work()\nend",
        "for i = (function() do return 1 end end)(), 3 do Work() end",
        "local callback = function() repeat Work() until done end\ncallback()",
    ],
)
def test_lua_blocks_preserve_immediately_following_function(body: str) -> None:
    text = "function First()\n" + body + "\nend\nfunction Second()\n    Finish()\nend"
    first_end = len(body.splitlines()) + 2
    assert _ranges(text) == [
        ("First", 1, first_end),
        ("Second", first_end + 1, first_end + 3),
    ]


@pytest.mark.parametrize(
    "first",
    [
        "function First() end",
        "local function First() if a then Work() elseif b then Other() end end",
        "function First() for i = 1, 3 do while a do Work() end end end",
        "function First() repeat Work() until done end",
    ],
)
def test_lua_declaration_line_is_part_of_block_scan(first: str) -> None:
    assert _ranges(first + "\nfunction Second() end") == [
        ("First", 1, 1),
        ("Second", 2, 2),
    ]


def test_lua_same_line_adjacent_functions_are_both_indexed() -> None:
    assert _ranges("function First() end; local function Second() end") == [
        ("First", 1, 1),
        ("Second", 1, 1),
    ]


@pytest.mark.parametrize(
    "body",
    [
        'local text = "if then elseif function repeat until end do"',
        "local text = 'if then elseif function repeat until end do'",
        r'''local text = "escaped \" end function"''',
        r"local text = 'escaped \' end function'",
        "-- if then elseif function repeat until end do",
        "local text = [[\nfunction Fake()\nif then elseif repeat do\n]]",
        "local text = [==[\nfunction Fake()\nend until do then\n]==]",
        "--[[\nfunction Fake()\nif then elseif repeat do\n]]",
        "--[==[\nfunction Fake()\nend until do then\n]==]",
        'local text = "--[=[" -- function Fake() if then do',
        "local value = 8 // 2; if value then\n    Work()\nend",
    ],
)
def test_lua_strings_comments_and_floor_division_do_not_change_blocks(
    body: str,
) -> None:
    text = "function First()\n" + body + "\nend\nfunction Second() end"
    first_end = len(body.splitlines()) + 2
    assert _ranges(text) == [
        ("First", 1, first_end),
        ("Second", first_end + 1, first_end + 1),
    ]


def test_lua_long_comments_outside_functions_do_not_create_fake_ranges() -> None:
    assert _ranges(
        "--[=[\nfunction Fake()\nend\n]=]\n"
        "local text = [[\nfunction AlsoFake()\nend\n]]\n"
        "function Real() end"
    ) == [("Real", 9, 9)]


def test_lua_elseif_does_not_mix_following_function_calls_or_object_codes() -> None:
    md = MapData(path="synthetic.w3x", name="Scoped calls")
    md.scripts = {
        "war3map.lua": "\n".join(
            (
                "function First()",
                "if a then",
                "    CreateUnit(Player(0), FourCC('hfoo'), 0, 0, 0)",
                "elseif b then",
                "    Work()",
                "end",
                "end",
                "function Second()",
                "    CreateItem(FourCC('ratf'), 0, 0)",
                "end",
            )
        ),
    }
    functions = build_script_function_index(md).functions
    assert [(row.name, row.start_line, row.end_line) for row in functions] == [
        ("First", 1, 7),
        ("Second", 8, 10),
    ]
    assert functions[0].called_functions == ("CreateUnit", "Work")
    assert functions[0].object_codes == ("hfoo",)
    assert functions[1].called_functions == ("CreateItem",)
    assert functions[1].object_codes == ("ratf",)


@pytest.mark.parametrize("newline", ["\n", "\r\n", "\r"])
def test_lua_comment_mask_preserves_line_endings(newline: str) -> None:
    assert _ranges(
        newline.join(
            (
                "function First()",
                "-- function Fake() then",
                "end",
                "function Next() end",
            )
        )
    ) == [("First", 1, 3), ("Next", 4, 4)]
