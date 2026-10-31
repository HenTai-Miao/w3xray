"""Malformed offline CASC bytes cannot become a successful partial resource."""

from __future__ import annotations

import hashlib
from pathlib import Path
import zlib

import pytest

from gametool.casc_source import (
    CascIndexEntry,
    CascUnsupportedError,
    _read_data_block,
    decode_blte,
)


def _framed(chunks: tuple[tuple[bytes, int], ...]) -> bytes:
    header = b"BLTE" + (12 + 24 * len(chunks)).to_bytes(4, "big")
    table = b"\x0f" + len(chunks).to_bytes(3, "big")
    for chunk, decoded_size in chunks:
        table += (
            len(chunk).to_bytes(4, "big")
            + decoded_size.to_bytes(4, "big")
            + hashlib.md5(chunk).digest()
        )
    return header + table + b"".join(chunk for chunk, _ in chunks)


def test_blte_reads_all_declared_plain_and_compressed_chunks() -> None:
    payload = _framed(((b"Nfirst", 5), (b"Z" + zlib.compress(b"second"), 6)))
    assert decode_blte(payload) == b"firstsecond"


@pytest.mark.parametrize(
    "payload",
    (
        b"BLTE\x00\x00\x00\x0c\x0f\xff\xff\xff",
        b"BLTE\x00\x00\x00\x0c\x0f\x00\x00\x00",
        _framed(((b"Nx", 1),)).replace(b"\x0f", b"\x0e", 1),
        _framed(((b"Nx", 2),)),
        _framed(((b"", 0),)),
        _framed(((b"Nx", 1),))[:-1],
        _framed(((b"Nx", 1),)) + b"unaccounted",
        _framed(((b"Nx", 1),))[:-1] + b"y",
        _framed(((b"Z" + zlib.compress(b"longer"), 1),)),
        _framed(((b"Z" + zlib.compress(b"x") + b"trailing", 1),)),
        b"BLTE\x00\x00\x00\x00Zbroken",
    ),
)
def test_blte_rejects_incomplete_or_conflicting_encoded_evidence(
    payload: bytes,
) -> None:
    with pytest.raises(CascUnsupportedError):
        decode_blte(payload)


def test_direct_blte_block_does_not_consume_the_following_archive_member(
    tmp_path: Path,
) -> None:
    payload = b"BLTE\x00\x00\x00\x00Nfirst"
    (tmp_path / "data.000").write_bytes(payload + b"another archive member")
    assert (
        _read_data_block(str(tmp_path), CascIndexEntry(0, 0, len(payload))) == b"first"
    )


def test_archive_block_rejects_a_short_declared_payload(tmp_path: Path) -> None:
    payload = b"BLTE\x00\x00\x00\x00Nx"
    block = b"\0" * 16 + (30 + len(payload) + 5).to_bytes(4, "little")
    (tmp_path / "data.000").write_bytes(block + b"\0" * 10 + payload)
    with pytest.raises(CascUnsupportedError, match="truncated"):
        _read_data_block(str(tmp_path), CascIndexEntry(0, 0, len(payload) + 5))
