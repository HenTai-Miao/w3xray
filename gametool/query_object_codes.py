"""Unambiguous object identities selected from query and report text."""

from __future__ import annotations

import re

from .object_codes import valid_object_code
from .query_coordinate_json import coordinate_json


_MARKED_CODE = re.compile(r"\[(.{4})\]|\((.{4})\)", re.DOTALL)


def code_from_text(text: str) -> str | None:
    """Accept exact raw IDs or explicit code annotations; never guess word fragments."""
    # Test the exact selection before trimming: whitespace is a legal ID byte.
    if valid_object_code(text):
        return text
    raw = text.strip()
    if valid_object_code(raw):
        return raw
    if len(raw) == 6 and raw[0] in "'\"" and raw[-1] == raw[0]:
        code = raw[1:-1]
        return code if valid_object_code(code) else None
    evidence = coordinate_json(raw)
    if evidence.present or evidence.invalid:
        # Complete live JSON can contain many objects. Its quotation or array
        # syntax is never an object-code annotation; ask for an exact selection.
        return None
    codes = {
        code
        for match in _MARKED_CODE.finditer(evidence.outside)
        for code in match.groups()
        if code is not None and valid_object_code(code)
    }
    return next(iter(codes)) if len(codes) == 1 else None
