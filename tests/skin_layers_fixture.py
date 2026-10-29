"""Product-only MPQ/object fixtures for complete binary-layer integration."""

from __future__ import annotations

import struct

from gametool.mpq_crypto import CRYPT_TABLE, hash_name_bytes


def _encrypt(data: bytes, seed: int) -> bytes:
    output = []
    other = 0xEEEEEEEE
    for (word,) in struct.iter_unpack("<I", data):
        other = (other + CRYPT_TABLE[0x400 + (seed & 255)]) & 0xFFFFFFFF
        output.append(word ^ ((seed + other) & 0xFFFFFFFF))
        seed = (((~seed & 0xFFFFFFFF) << 21) + 0x11111111 | (seed >> 11)) & 0xFFFFFFFF
        other = (word + other + (other << 5) + 3) & 0xFFFFFFFF
    return struct.pack(f"<{len(output)}I", *output)


def mpq(files: dict[str, bytes], *, listed: bool = True) -> bytes:
    if listed:
        files = {**files, "(listfile)": "\r\n".join(files).encode("utf-8")}
    count = 1 << (len(files) * 2).bit_length()
    hashes = [b"\xff" * 16] * count
    blocks = []
    payloads = []
    offset = 32 + count * 16 + len(files) * 16
    for index, (name, payload) in enumerate(files.items()):
        encoded = name.encode("utf-8")
        slot = hash_name_bytes(encoded, 0) & (count - 1)
        while hashes[slot] != b"\xff" * 16:
            slot = (slot + 1) & (count - 1)
        hashes[slot] = struct.pack(
            "<IIHHI",
            hash_name_bytes(encoded, 1),
            hash_name_bytes(encoded, 2),
            0,
            0,
            index,
        )
        blocks.append(
            struct.pack("<IIII", offset, len(payload), len(payload), 0x81000000)
        )
        payloads.append(payload)
        offset += len(payload)
    return b"".join(
        (
            struct.pack(
                "<4sIIHHIIII",
                b"MPQ\x1a",
                32,
                offset,
                0,
                3,
                32,
                32 + count * 16,
                count,
                len(files),
            ),
            _encrypt(b"".join(hashes), hash_name_bytes(b"(hash table)", 3)),
            _encrypt(b"".join(blocks), hash_name_bytes(b"(block table)", 3)),
            *payloads,
        )
    )


def object_file(
    ext: str,
    fields: tuple[tuple[str, str | int, int, int], ...],
    *,
    code: str = "S001",
    base: str = "ratf",
) -> bytes:
    mods = []
    for key, value, level, pointer in fields:
        storage = 0 if isinstance(value, int) else 3
        payload = key.encode("latin-1") + struct.pack("<i", storage)
        if ext in {"w3a", "w3q", "w3d"}:
            payload += struct.pack("<ii", level, pointer)
        payload += (
            struct.pack("<i", value)
            if isinstance(value, int)
            else value.encode("utf-8") + b"\0"
        )
        mods.append(payload + b"\0" * 4)
    return (
        struct.pack("<iii", 2, 0, 1)
        + base.encode("latin-1")
        + code.encode("latin-1")
        + struct.pack("<i", len(mods))
        + b"".join(mods)
    )


def slk(columns: tuple[str, ...], rows: tuple[tuple[str, ...], ...]) -> bytes:
    lines = ["ID;P", f"B;X{len(columns)};Y{len(rows) + 1}"]
    for y, row in enumerate((columns, *rows), 1):
        for x, cell in enumerate(row, 1):
            lines.append(f'C;X{x};Y{y};K"{cell}"')
    return ("\n".join((*lines, "E")) + "\n").encode("utf-8")
