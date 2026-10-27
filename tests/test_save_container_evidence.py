"""Both block-header widths, exact source records and confirmed-prefix recovery."""

from __future__ import annotations

import struct

import pytest

from gametool.save_container import inspect_save_container, unpack_save_container
from tests.save_structure_fixture import container_bytes


@pytest.mark.parametrize("shape", ("<III", "<HHI"))
def test_block_shapes_and_real_header_crc_have_complete_byte_provenance(
    shape: str,
) -> None:
    raw = b"saved-state\0H001" * 3
    blob = container_bytes(raw, shape=shape, chunks=16, crc_header=True)
    evidence = inspect_save_container(blob)
    assert evidence.complete, evidence.diagnostics
    assert evidence.header_checksum_ok
    assert evidence.block_header == shape
    assert evidence.raw == raw
    encoded = evidence.to_dict(blob)
    assert encoded["tail_hex"] == ""
    assert unpack_save_container(blob).raw == raw
    for block in evidence.blocks:
        assert blob[block.offset : block.data_offset] == block.header_bytes
        assert block.raw_offset < len(raw)


def test_bad_later_block_keeps_only_verified_prefix_and_complete_tail() -> None:
    raw = b"prefixfirstsecond"
    blob = bytearray(container_bytes(raw, chunks=6))
    whole = inspect_save_container(bytes(blob))
    broken = whole.blocks[1]
    blob[broken.data_offset] ^= 0xFF
    evidence = inspect_save_container(bytes(blob))
    assert not evidence.complete
    assert evidence.raw == raw[:6]
    assert evidence.consumed == broken.offset
    assert evidence.to_dict(bytes(blob))["tail_hex"] == blob[broken.offset :].hex()


def test_file_size_and_crc_conflicts_remain_explicit() -> None:
    blob = bytearray(container_bytes(b"payload", chunks=7, crc_header=True))
    struct.pack_into("<I", blob, 32, len(blob) + 1)
    evidence = inspect_save_container(bytes(blob))
    assert not evidence.complete and evidence.raw == b"payload"
    assert any("file_size" in note for note in evidence.diagnostics)
    assert any("header checksum" in note for note in evidence.diagnostics)


def test_truncated_block_count_retains_verified_blocks() -> None:
    blob = bytearray(container_bytes(b"firstsecond", chunks=5))
    struct.pack_into("<I", blob, 44, 0xFFFFFFFF)
    evidence = inspect_save_container(bytes(blob))
    assert not evidence.complete
    assert evidence.raw == b"firstsecond"
    assert any("block count" in note for note in evidence.diagnostics)
