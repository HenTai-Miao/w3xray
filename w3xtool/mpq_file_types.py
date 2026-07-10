"""File-signature guesses used for anonymous MPQ exports."""

from __future__ import annotations


def guess_extension(data: bytes) -> str:
    """Return a conservative extension inferred from an extracted file header."""
    if len(data) < 4:
        return "bin"
    header = data[:4]
    if header in (b"BLP1", b"BLP2"):
        return "blp"
    if header == b"MDLX":
        return "mdx"
    if header == b"DDS ":
        return "dds"
    if header == b"RIFF":
        return "wav"
    if header[:3] == b"ID3" or header[:2] == b"\xff\xfb":
        return "mp3"
    if header == b"OggS":
        return "ogg"
    if header in (b"\x00\x01\x00\x00", b"OTTO", b"true"):
        return "ttf"
    if header[:3] == b"ID;":
        return "slk"
    if header == b"HM3W":
        return "w3m"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if header[:2] == b"\xff\xd8":
        return "jpg"
    if header[:2] == b"BM":
        return "bmp"
    try:
        sample = data[:512].decode("ascii").lstrip().lower()
    except UnicodeDecodeError:
        return "tga" if len(data) > 18 and data[2] in (1, 2, 3, 9, 10, 11) else "bin"
    if sample[:7] == "version" or sample[:2] == "//":
        return "mdl"
    if sample[:8] == "function" or sample[:6] == "global":
        return "mdl"
    return "txt"
