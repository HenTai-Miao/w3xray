"""JASS/Lua save-call argument parsing for save analysis."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Final

from .save_api_catalog import is_hashtable_key_api

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


_INTERESTING_RE: Final = re.compile(r"['\"(),]")
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


def extract_call_args(line: str, start: int) -> tuple[str, ...]:
    """Extract top-level comma-separated arguments from ``line[start:]``.

    这是全部脚本扫描里调用最多的热函数（单图几十万次）；逐字符的
    Python 状态机会在每个字符上做列表追加，改成用预编译正则跳到
    下一个引号/括号/逗号，普通字符段由 C 层扫描，参数用切片取出。
    """
    args: list[str] = []
    chunk_start = start
    depth = 0
    index = start
    search = _INTERESTING_RE.search
    while True:
        match = search(line, index)
        if match is None:
            return ()
        index = match.start()
        char = line[index]
        if char in "'\"":
            index = _skip_quoted(line, index)
            continue
        if char == "(":
            depth += 1
            index += 1
            continue
        if char == ")":
            if depth == 0:
                value = line[chunk_start:index].strip()
                if value or args:
                    args.append(value)
                    return tuple(args)
                return ()
            depth -= 1
            index += 1
            continue
        if char == ",":
            if depth == 0:
                args.append(line[chunk_start:index].strip())
                chunk_start = index + 1
            index += 1
            continue
        index += 1


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
    if value.startswith("StringHash("):
        nested = extract_call_args(value, len("StringHash("))
        return clean_arg(nested[0]) if nested else value
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
        return unescape_arg(value[1:-1])
    return value


def unescape_arg(text: str) -> str:
    """Unescape common JASS string escapes used in resource/save paths."""
    return text.replace("\\\\", "\\").replace('\\"', '"')
