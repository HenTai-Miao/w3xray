"""JASS/Lua save-call argument parsing for save analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .save_api_catalog import is_hashtable_key_api
from .script_lexing import ScriptViews, literal_string_value, script_views

_FILE_ARG_INDEX: Final = {
    "InitGameCache": 0,
    "Preload": 0,
    "PreloadGenEnd": 0,
}
_GAMECACHE_KEY_APIS: Final = {
    "StoreInteger",
    "StoreReal",
    "StoreBoolean",
    "StoreString",
    "StoreUnit",
    "GetStoredInteger",
    "GetStoredReal",
    "GetStoredBoolean",
    "GetStoredString",
    "GetStoredUnit",
    "FlushStoredMission",
    "SyncStoredInteger",
    "SyncStoredReal",
    "SyncStoredBoolean",
    "SyncStoredString",
}
_SYNC_ARG_INDEX: Final = {
    "BlzSendSyncData": 0,
    "BlzTriggerRegisterPlayerSyncEvent": 2,
}
_PLATFORM_KEY_ARG1: Final = {
    "DzAPI_Map_SaveServerValue",
    "DzAPI_Map_GetServerValue",
    "DzAPI_Map_SavePublicArchive",
    "DzAPI_Map_GetPublicArchive",
    "KKAPI_SaveServerValue",
    "KKAPI_GetServerValue",
}
_PLATFORM_SECTION_KEY_ARG12: Final = {
    "DzAPI_Map_StoreInteger",
    "DzAPI_Map_GetStoredInteger",
}


@dataclass(frozen=True, slots=True)
class SaveCallContext:
    file_path: str = ""
    section: str = ""
    key: str = ""
    sync_prefix: str = ""


_INTERESTING_RE: Final = re.compile(
    r"//|--|['\"(),{}\[\]]|\b(?:function|if|for|while|do|repeat|end|until)\b"
)
_LONG_BRACKET_RE: Final = re.compile(r"\[(=*)\[")
_LINE_COMMENT_END_RE: Final = re.compile(r"[\r\n]")
_QUOTE_SCAN_BY_CHAR: Final = {
    "'": re.compile(r"\\.|'"),
    '"': re.compile(r'\\.|"'),
}


def structured_context(name: str, args: tuple[str, ...]) -> SaveCallContext:
    """Extract file/key/sync context from a matched save-style API call."""
    file_path = _arg_at(args, _FILE_ARG_INDEX.get(name))
    section = ""
    key = ""
    if name in _GAMECACHE_KEY_APIS and len(args) >= 3:
        section = clean_arg(args[1])
        key = clean_arg(args[2])
    if is_hashtable_key_api(name) and len(args) >= 3:
        section = clean_arg(args[1])
        key = clean_arg(args[2])
    if name == "FlushChildHashtable" and len(args) >= 2:
        section = clean_arg(args[1])
    if name == "StringHash" and args:
        key = clean_arg(args[0])
    if name == "GetHandleId" and args:
        section = f"GetHandleId({clean_arg(args[0])})"
    if name in _PLATFORM_KEY_ARG1 and len(args) >= 2:
        key = clean_arg(args[1])
    if name in _PLATFORM_SECTION_KEY_ARG12 and len(args) >= 3:
        section = clean_arg(args[1])
        key = clean_arg(args[2])
    return SaveCallContext(
        file_path=file_path,
        section=section,
        key=key,
        sync_prefix=_arg_at(args, _SYNC_ARG_INDEX.get(name)),
    )


def _arg_at(args: tuple[str, ...], index: int | None) -> str:
    if index is None or index >= len(args):
        return ""
    return clean_arg(args[index])


def extract_call_args(
    line: str | ScriptViews,
    start: int,
    *,
    lua: bool | None = None,
    mask_strings: bool = False,
) -> tuple[str, ...]:
    """Read balanced arguments, ignoring comments and opaque string contents.

    Lua table/index delimiters and anonymous-function blocks remain inside
    their argument. The scan uses an explicit stack and has no depth ceiling.
    """
    prepared = isinstance(line, ScriptViews)
    if isinstance(line, ScriptViews):
        lua = line.lua if lua is None else lua
        original = line.arguments
        line = line.code if mask_strings else original
    else:
        original = line
    args: list[str] = []
    chunk_start = index = start
    brackets: list[str] = []
    blocks: list[str] = []

    def argument(stop: int) -> tuple[str, bool]:
        # A raw-string caller may have handed us a whole large script. Only
        # materialize the current argument; its unrelated tail stays untouched.
        fragment = original[chunk_start:stop]
        if prepared:
            return line[chunk_start:stop].strip(), bool(fragment.strip())
        view = script_views(fragment, lua=lua)
        return (
            (view.code if mask_strings else view.arguments).strip(),
            bool(view.arguments.strip()),
        )

    while (match := _INTERESTING_RE.search(line, index)) is not None:
        index = match.start()
        token = match.group()
        if token in {"//", "--"}:
            if (token == "//" and lua is True) or (token == "--" and lua is False):
                index = match.end()
                continue
            opening = (
                _LONG_BRACKET_RE.match(line, match.end()) if token == "--" else None
            )
            if opening is not None:
                close = "]" + opening.group(1) + "]"
                end = line.find(close, opening.end())
                if end < 0:
                    return ()
                index = end + len(close)
            else:
                end_of_line = _LINE_COMMENT_END_RE.search(line, match.end())
                if end_of_line is None:
                    return ()
                index = end_of_line.end()
            continue
        if token in {"'", '"'}:
            index = _skip_quoted(line, index)
            continue
        if token == "[" and lua is not False:
            opening = _LONG_BRACKET_RE.match(line, index)
            if opening is not None:
                close = "]" + opening.group(1) + "]"
                end = line.find(close, opening.end())
                if end < 0:
                    return ()
                index = end + len(close)
                continue
        if token in {"(", "[", "{"}:
            brackets.append({"(": ")", "[": "]", "{": "}"}[token])
        elif token in {")", "]", "}"}:
            if not brackets:
                if token != ")" or blocks:
                    return ()
                value, present = argument(index)
                if present or args:
                    args.append(value)
                return tuple(args)
            if brackets.pop() != token:
                return ()
        elif token == ",":
            if not brackets and not blocks:
                args.append(argument(index)[0])
                chunk_start = index + 1
        elif lua is True:
            if token in {"function", "if", "for", "while", "repeat"}:
                blocks.append(token)
            elif token == "do":
                if blocks and blocks[-1] in {"for", "while"}:
                    blocks[-1] = "do"
                else:
                    blocks.append("do")
            elif blocks and (
                (token == "end" and blocks[-1] in {"function", "if", "do"})
                or (token == "until" and blocks[-1] == "repeat")
            ):
                blocks.pop()
        index = match.end()
    return ()


def _skip_quoted(line: str, start: int) -> int:
    """Return the index just past the closing quote of ``line[start]``."""
    pattern = _QUOTE_SCAN_BY_CHAR[line[start]]
    index = start + 1
    while True:
        match = pattern.search(line, index)
        if match is None:
            return len(line)
        if match.group(0).startswith("\\"):
            index = match.end()
            continue
        return match.end()


def clean_arg(arg: str) -> str:
    """Return a readable argument value, unwrapping quoted/StringHash values."""
    value = arg.strip()
    while value.startswith("StringHash("):
        nested = extract_call_args(value, len("StringHash("))
        if not nested:
            return value
        value = nested[0].strip()
        # A direct chain needs one validation scan and one prefix walk, rather
        # than rescanning the entire suffix once for every nested StringHash.
        cursor = last_start = 0
        while value.startswith("StringHash(", cursor):
            last_start = cursor
            cursor += len("StringHash(")
            while cursor < len(value) and value[cursor].isspace():
                cursor += 1
        if cursor:
            inner = extract_call_args(value, cursor)
            if not inner:
                closing = value.find(")", cursor)
                return value[last_start : closing + 1] if closing >= 0 else value
            value = inner[0].strip()
    literal = literal_string_value(value)
    return value if literal is None else literal


def unescape_arg(text: str) -> str:
    """Unescape common JASS string escapes used in resource/save paths."""
    return text.replace("\\\\", "\\").replace('\\"', '"')
