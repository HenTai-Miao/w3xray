"""Real-reader regressions for the current-session empty compressed blocks."""

from __future__ import annotations

from collections import Counter
import csv
from pathlib import Path
import struct
from typing import cast

import pytest

from gametool.extraction_completeness import (
    BlockProbe,
    ExtractionArchive,
    build_extraction_completeness_from_archive,
)
from gametool.knowledge_unknown_exports import (
    UnknownArchive,
    write_unknown_files_from_archive,
)
from gametool.map_data import MapData
from gametool.mpq import FLAG_COMPRESS, FLAG_ENCRYPTED, FLAG_EXISTS, MPQArchive
from gametool.mpq_block_reader import (
    MPQBlockError,
    read_mpq_block_anonymous,
    recover_mpq_block_key,
)
from gametool.mpq_crypto import CRYPT_TABLE
from gametool.mpq_layout import ArchiveBytes, _Block


def _encrypt(data: bytes, key: int) -> bytes:
    count = len(data) // 4
    seed1, seed2 = key & 0xFFFF_FFFF, 0xEEEE_EEEE
    encrypted: list[int] = []
    for value in struct.unpack(f"<{count}I", data[: count * 4]):
        seed2 = (seed2 + CRYPT_TABLE[0x400 + (seed1 & 0xFF)]) & 0xFFFF_FFFF
        encrypted.append((value ^ ((seed1 + seed2) & 0xFFFF_FFFF)) & 0xFFFF_FFFF)
        seed1 = (
            ((~seed1 & 0xFFFF_FFFF) << 0x15) + 0x1111_1111 | (seed1 >> 0x0B)
        ) & 0xFFFF_FFFF
        seed2 = (value + seed2 + (seed2 << 5) + 3) & 0xFFFF_FFFF
    return struct.pack(f"<{count}I", *encrypted) + data[count * 4 :]


class _Archive:
    path = "synthetic.w3x"
    archive_offset = 0
    sector_size = 4096
    _data: ArchiveBytes

    def __init__(self) -> None:
        key = 0x1234_5678
        bad_encrypted = _encrypt(struct.pack("<II", 8, 11), key - 1) + _encrypt(
            b"\x02xx", key
        )
        self._data = b"plain" + bad_encrypted
        self.blocks = (
            _Block(0, 5, 5, FLAG_EXISTS),
            _Block(5, 0, 0, FLAG_EXISTS | FLAG_COMPRESS),
            _Block(
                5, len(bad_encrypted), 16, FLAG_EXISTS | FLAG_COMPRESS | FLAG_ENCRYPTED
            ),
        )
        self.read_counts: Counter[int] = Counter()

    def list_files(self) -> list[str]:
        return []

    def has_file(self, _name: str) -> bool:
        return False

    def block_index_of(self, _name: str) -> int | None:
        return None

    def iter_blocks(self) -> tuple[tuple[int, _Block], ...]:
        return tuple(enumerate(self.blocks))

    def recover_block_key(self, block: _Block) -> int | None:
        return recover_mpq_block_key(self, block)

    def read_block_anon(self, block: BlockProbe) -> bytes | None:
        encoded = cast(_Block, cast(object, block))
        self.read_counts[self.blocks.index(encoded)] += 1
        return read_mpq_block_anonymous(self, encoded)


def test_completeness_uses_each_real_decode_once_and_matches_export_manifest(
    tmp_path: Path,
) -> None:
    archive = _Archive()
    # Recovering an encryption key alone does not prove the sector can decode.
    assert archive.recover_block_key(archive.blocks[2]) is not None
    report = build_extraction_completeness_from_archive(
        MapData(path=archive.path, name="真实读取边界"),
        cast(ExtractionArchive, cast(object, archive)),
    )

    assert report.recoverable_anonymous_count == 1
    assert report.raw_fallback_count == 2
    assert archive.read_counts == {0: 1, 1: 1, 2: 1}
    assert (
        write_unknown_files_from_archive(
            cast(UnknownArchive, cast(object, archive)), str(tmp_path)
        )
        == 4
    )
    with (tmp_path / "Unknown_manifest.tsv").open(
        "r", encoding="utf-8", newline=""
    ) as handle:
        rows = tuple(csv.DictReader(handle, delimiter="\t"))
    assert Counter(row["kind"] for row in rows) == {"Unknown": 1, "UnknownRaw": 2}
    assert (tmp_path / "UnknownRaw/block_000001.raw").read_bytes() == b""
    assert (tmp_path / "UnknownRaw/block_000002.raw").read_bytes() == archive._data[5:]


@pytest.mark.parametrize(
    ("payload", "flags", "valid"),
    (
        (b"", FLAG_EXISTS, True),
        (struct.pack("<I", 4), FLAG_EXISTS | FLAG_COMPRESS, True),
        (b"", FLAG_EXISTS | FLAG_COMPRESS, False),
    ),
)
def test_named_and_anonymous_empty_readers_share_the_existing_layout_contract(
    payload: bytes, flags: int, valid: bool
) -> None:
    archive = object.__new__(MPQArchive)
    archive._data = payload
    archive.archive_offset = 0
    archive.sector_size = 4096
    block = _Block(0, len(payload), 0, flags)

    if valid:
        assert archive._read_block(block, "empty.dat") == b""
        assert archive.read_block_anon(block) == b""
    else:
        with pytest.raises(MPQBlockError, match="偏移表被截断"):
            archive._read_block(block, "empty.dat")
        assert archive.read_block_anon(block) is None
