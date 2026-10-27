"""Four-byte identities and complete object-field reference lists."""


def valid_object_code(code: str) -> bool:
    return len(code) == 4 and all(ord(char) <= 255 for char in code)


def encode_object_id_query(code: str) -> str:
    """Select one exact case-sensitive FourCC, independently of search syntax."""
    if not valid_object_code(code):
        raise ValueError("对象 ID 选择器需要完整四字节 Latin-1 身份")
    return 'id:="' + code.replace('"', '""') + '"'


def decode_object_id_query(query: str) -> str | None:
    """Recognize a whole canonical ID selector; preserve every payload byte.

    Doubled double quotes encode one quote. Backslashes, whitespace, Warcraft
    color markers and Boolean punctuation have no special meaning here. Other
    query spellings keep their existing search/name semantics.
    """
    if not query.startswith('id:="'):
        return None
    chars: list[str] = []
    position = 5
    while position < len(query):
        char = query[position]
        if char == '"':
            if position + 1 < len(query) and query[position + 1] == '"':
                chars.append('"')
                position += 2
                continue
            if position != len(query) - 1:
                return None
            code = "".join(chars)
            return code if valid_object_code(code) else None
        chars.append(char)
        position += 1
    return None


def unquote_legacy_object_code(value: str) -> str:
    """Decode a known legacy quote only in a declared four-byte identity role."""
    if len(value) == 5:
        start = _start(value, 0)
        if value[start : start + 2] in ("'=", "'+", "'-", "'@"):
            code = value[:start] + value[start + 1 :]
            if valid_object_code(code):
                return code
    return value


def _start(text: str, position: int) -> int:
    while position < len(text) and text[position].isspace():
        position += 1
    return position


def _literal_code(text: str, start: int, end: int) -> str | None:
    if end - start == 4:
        code = text[start:end]
        if valid_object_code(code):
            return code
    return None


def _end(text: str, start: int, end: int) -> int:
    while end > start and text[end - 1].isspace():
        end -= 1
    return end


def _ending_code(
    text: str, start: int, stripped_start: int, end: int
) -> tuple[str, bool] | None:
    # Boundary whitespace belongs to an exact four-byte literal. Only longer
    # spellings may contain surrounding list formatting.
    code = _literal_code(text, start, end)
    if code is not None:
        return code, False
    end = _end(text, stripped_start, end)
    code = _literal_code(text, stripped_start, end)
    if code is not None:
        return code, False
    if end - start >= 6 and text[end - 1] == ")" and text[end - 6] == "(":
        code = _literal_code(text, end - 5, end - 1)
        if code is not None:
            # ``abc(,I01)`` is both the raw pair ``abc(``, ``I01)`` and a
            # terminal reference to ``,I01``. Neither reading confirms an ID.
            prefix = _literal_code(text, start, end - 5) or _literal_code(
                text, stripped_start, end - 5
            )
            return code, code[0] in ",|" and prefix is not None
    return None


def _boundaries(text: str) -> tuple[int, ...]:
    boundaries = [index for index, char in enumerate(text) if char in ",|"]
    boundaries.append(len(text))
    protected: set[int] = set()
    # Work from the right so a delimiter inside a complete suffix cannot make
    # an earlier, overlapping fake suffix protect another delimiter.
    for boundary in reversed(boundaries):
        if boundary in protected:
            continue
        end = _end(text, 0, boundary)
        if (
            end >= 6
            and text[end - 1] == ")"
            and text[end - 6] == "("
            and _literal_code(text, end - 5, end - 1) is not None
        ):
            protected.update(
                index for index in range(end - 5, end - 1) if text[index] in ",|"
            )
    return tuple(boundary for boundary in boundaries if boundary not in protected)


def field_object_codes(value: str) -> tuple[str, ...]:
    """Read raw codes or terminal name(code), keeping case, order and duplicates.

    Commas and legacy pipes separate confirmed reference tokens. A complete
    four-byte literal or terminal code is recognized before splitting its
    internal punctuation. Keep source values unchanged at every caller.
    Ambiguous complete raw-list/name spellings remain source evidence only.
    Only fixed-size suffixes are inspected, including for arbitrarily long names.
    """
    codes: list[str] = []
    start = fragment = 0
    stripped_start = stripped_fragment = _start(value, 0)
    for end in _boundaries(value):
        candidate = _ending_code(value, start, stripped_start, end)
        if fragment != start:
            recovered = _ending_code(value, fragment, stripped_fragment, end)
            # A longer unresolved name must not hide ambiguity in its final
            # fragment and thereby promote one of the competing identities.
            if candidate is None or recovered is not None and recovered[1]:
                candidate = recovered
        if candidate is not None:
            code, ambiguous = candidate
            if not ambiguous:
                codes.append(code)
            start = end + 1
            stripped_start = _start(value, start)
        fragment = end + 1
        stripped_fragment = _start(value, fragment)
    return tuple(codes)
