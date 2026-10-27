"""Bounded, read-only decoding of Warcraft III .w3z/.w3v save containers."""

from __future__ import annotations

import struct
import zlib
from dataclasses import dataclass
from typing import Final

SAVE_CONTAINER_SIGNATURE: Final = b"Warcraft III recorded game\x1a\x00"
_HEADER_FIXED_BYTES: Final = 48
_BLOCK_HEADER_BYTES: Final = 12
MAX_SAVE_CONTAINER_RAW_BYTES: Final[int | None] = None


class SaveContainerError(ValueError):
    """Raised when a save container violates its documented binary format."""

    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True, slots=True)
class SaveContainerHeader:
    header_size: int
    file_size: int
    header_version: int
    decompressed_size: int
    block_count: int
    subheader: bytes


@dataclass(frozen=True, slots=True)
class SaveContainerBlock:
    index: int
    offset: int
    compressed_size: int
    original_size: int
    checksum: int
    checksum_ok: bool
    data_offset: int = 0
    raw_offset: int = 0
    header_bytes: bytes = b""


@dataclass(frozen=True, slots=True)
class SaveContainerPayload:
    header: SaveContainerHeader
    blocks: tuple[SaveContainerBlock, ...]
    raw: bytes


@dataclass(frozen=True, slots=True)
class SaveContainerInspection:
    header: SaveContainerHeader | None
    blocks: tuple[SaveContainerBlock, ...]
    raw: bytes
    complete: bool
    consumed: int
    block_header: str
    diagnostics: tuple[str, ...]
    header_checksum_ok: bool | None = None
    header_checksum_offset: int | None = None
    header_checksum_span: int | None = None

    def to_dict(self, payload: bytes) -> dict[str, object]:
        header = self.header
        return {
            "signature": payload[: len(SAVE_CONTAINER_SIGNATURE)].hex(),
            "expected_signature": SAVE_CONTAINER_SIGNATURE.hex(),
            "state": "confirmed" if self.complete else "partial",
            "complete": self.complete,
            "endianness": "little",
            "block_header": self.block_header,
            "header": None
            if header is None
            else {
                "header_size": header.header_size,
                "file_size": header.file_size,
                "header_version": header.header_version,
                "decompressed_size": header.decompressed_size,
                "block_count": header.block_count,
                "raw_hex": payload[: header.header_size].hex(),
                "subheader_offset": _HEADER_FIXED_BYTES,
                "subheader_hex": header.subheader.hex(),
                "checksum_ok": self.header_checksum_ok,
                "checksum_offset": self.header_checksum_offset,
                "checksum_span": self.header_checksum_span,
                "fields": [
                    {
                        "name": name,
                        "offset": 28 + index * 4,
                        "end": 32 + index * 4,
                        "value": value,
                        "raw_hex": payload[28 + index * 4 : 32 + index * 4].hex(),
                    }
                    for index, (name, value) in enumerate(
                        (
                            ("header_size", header.header_size),
                            ("file_size", header.file_size),
                            ("header_version", header.header_version),
                            ("decompressed_size", header.decompressed_size),
                            ("block_count", header.block_count),
                        )
                    )
                ],
            },
            "blocks": [
                {
                    "index": block.index,
                    "offset": block.offset,
                    "data_offset": block.data_offset,
                    "raw_offset": block.raw_offset,
                    "compressed_size": block.compressed_size,
                    "original_size": block.original_size,
                    "checksum": block.checksum,
                    "checksum_ok": block.checksum_ok,
                    "header_hex": block.header_bytes.hex(),
                    "compressed_hex": payload[
                        block.data_offset : block.data_offset + block.compressed_size
                    ].hex(),
                }
                for block in self.blocks
            ],
            "raw_bytes": len(self.raw),
            "consumed": self.consumed,
            "tail_offset": self.consumed,
            "tail_hex": payload[self.consumed :].hex(),
            "diagnostics": list(self.diagnostics),
        }


def looks_like_save_container(payload: bytes) -> bool:
    """Return True when the payload starts with the recorded-save signature."""
    return payload.startswith(SAVE_CONTAINER_SIGNATURE)


def parse_save_container_header(payload: bytes) -> SaveContainerHeader:
    """Parse and bounds-check the fixed recorded-save header."""
    return _header(payload, check_count=True)


def _header(payload: bytes, *, check_count: bool) -> SaveContainerHeader:
    if len(payload) < _HEADER_FIXED_BYTES:
        raise SaveContainerError(
            f"file too small for save header: {len(payload)} bytes"
        )
    if not looks_like_save_container(payload):
        raise SaveContainerError("bad save container signature")
    header_size, file_size, header_version, decompressed_size, block_count = (
        struct.unpack_from("<5I", payload, len(SAVE_CONTAINER_SIGNATURE))
    )
    if header_size < _HEADER_FIXED_BYTES or header_size > len(payload):
        raise SaveContainerError(f"bad header_size: {header_size}")
    if check_count and block_count > (len(payload) - header_size) // 8:
        raise SaveContainerError(
            f"block count exceeds available headers: {block_count}"
        )
    return SaveContainerHeader(
        header_size=header_size,
        file_size=file_size,
        header_version=header_version,
        decompressed_size=decompressed_size,
        block_count=block_count,
        subheader=bytes(payload[_HEADER_FIXED_BYTES:header_size]),
    )


def unpack_save_container(
    payload: bytes,
    *,
    max_raw_bytes: int | None = MAX_SAVE_CONTAINER_RAW_BYTES,
) -> SaveContainerPayload:
    """Strictly decode one container: verified checksums, bounded expansion, no writes.

    Every block's declared original size is checked against the remaining raw
    budget before any decompression, mirroring the declared-expansion rule used
    for MPQ members.
    """
    inspected = inspect_save_container(payload, max_raw_bytes=max_raw_bytes)
    if not inspected.complete or inspected.header is None:
        raise SaveContainerError("; ".join(inspected.diagnostics))
    return SaveContainerPayload(inspected.header, inspected.blocks, inspected.raw)


def inspect_save_container(
    payload: bytes,
    *,
    max_raw_bytes: int | None = MAX_SAVE_CONTAINER_RAW_BYTES,
) -> SaveContainerInspection:
    """Inspect both documented block widths; retain verified blocks on failure."""
    if max_raw_bytes is not None and (
        type(max_raw_bytes) is not int or max_raw_bytes < 0
    ):
        raise ValueError("max_raw_bytes must be a nonnegative integer or None")
    try:
        header = _header(payload, check_count=False)
    except SaveContainerError as exc:
        return SaveContainerInspection(None, (), b"", False, 0, "", (exc.reason,))
    candidates: list[SaveContainerInspection] = []
    for shape in ("<III", "<HHI"):
        candidates.append(_inspect_blocks(payload, header, shape, max_raw_bytes))
    complete = [candidate for candidate in candidates if candidate.complete]
    if complete:
        result = complete[0]
        if any(candidate.raw != result.raw for candidate in complete[1:]):
            return SaveContainerInspection(
                header,
                (),
                b"",
                False,
                header.header_size,
                "ambiguous",
                ("ambiguous container block headers",),
            )
    else:
        result = max(
            candidates,
            key=lambda candidate: (len(candidate.blocks), len(candidate.raw)),
        )
    checksum_ok: bool | None = None
    # The version-0 fixed header is 64 bytes (CRC at 60), version 1 is
    # 68 bytes (CRC at 64). Header extensions are outside that CRC span.
    # See gowarcraft3/file/w3g/header.go DecodeHeader, independently checked
    # against the encoded 16-byte v0 and 20-byte v1 subheader fields.
    crc_at = {0: 60, 1: 64}.get(header.header_version)
    crc_span: int | None = None
    diagnostics = list(result.diagnostics)
    if header.header_version not in (0, 1):
        diagnostics.append(
            f"unknown header_version {header.header_version}; opaque subheader retained"
        )
    if crc_at is not None and crc_at + 4 <= header.header_size:
        crc_span = crc_at + 4
        stored = struct.unpack_from("<I", payload, crc_at)[0]
        copied = bytearray(payload[:crc_span])
        copied[crc_at : crc_at + 4] = b"\0" * 4
        checksum_ok = stored == (zlib.crc32(copied) & 0xFFFFFFFF)
        if not checksum_ok:
            diagnostics.append(f"header checksum mismatch at offset {crc_at}")
    if header.file_size != len(payload):
        diagnostics.append(
            f"container file_size {header.file_size} does not match actual {len(payload)}"
        )
    return SaveContainerInspection(
        header,
        result.blocks,
        result.raw,
        result.complete and not diagnostics,
        result.consumed,
        result.block_header,
        tuple(diagnostics),
        checksum_ok,
        crc_at if crc_span is not None else None,
        crc_span,
    )


def _inspect_blocks(
    payload: bytes, header: SaveContainerHeader, shape: str, max_raw_bytes: int | None
) -> SaveContainerInspection:
    raw = bytearray()
    blocks: list[SaveContainerBlock] = []
    offset = header.header_size
    header_bytes = struct.calcsize(shape)
    diagnostics: list[str] = []
    if header.block_count > (len(payload) - offset) // header_bytes:
        diagnostics.append(
            f"block count exceeds available headers: {header.block_count}"
        )
    for index in range(header.block_count):
        try:
            block, chunk, end = _decode_block(
                payload, offset, index, len(raw), shape, max_raw_bytes
            )
        except SaveContainerError as exc:
            diagnostics.append(exc.reason)
            break
        blocks.append(block)
        raw.extend(chunk)
        offset = end
    else:
        if offset != len(payload):
            diagnostics.append(f"trailing bytes after blocks: {len(payload) - offset}")
        if len(raw) != header.decompressed_size:
            diagnostics.append(
                f"container decompressed size does not match declared {header.decompressed_size}: {len(raw)}"
            )
    return SaveContainerInspection(
        header,
        tuple(blocks),
        bytes(raw),
        not diagnostics,
        offset,
        shape,
        tuple(diagnostics),
    )


def _decode_block(
    payload: bytes,
    offset: int,
    index: int,
    raw_offset: int,
    shape: str,
    max_raw_bytes: int | None,
) -> tuple[SaveContainerBlock, bytes, int]:
    block_header_bytes = struct.calcsize(shape)
    if offset + block_header_bytes > len(payload):
        raise SaveContainerError(f"block {index}: missing block header")
    compressed_size, original_size, checksum = struct.unpack_from(
        shape, payload, offset
    )
    data_offset = offset + block_header_bytes
    data_end = data_offset + compressed_size
    if data_end > len(payload):
        raise SaveContainerError(
            f"block {index}: compressed payload extends beyond file"
        )
    compressed = payload[data_offset:data_end]
    expected = _block_checksum(compressed, compressed_size, original_size, shape=shape)
    if checksum != expected:
        raise SaveContainerError(
            f"block {index} checksum mismatch: got {checksum:08x}, expected {expected:08x}"
        )
    if max_raw_bytes is not None and original_size > max_raw_bytes - raw_offset:
        raise SaveContainerError(
            f"block {index} declared size {original_size} exceeds raw budget {max_raw_bytes}"
        )
    try:
        decompressor = zlib.decompressobj(wbits=15)
        # zlib treats max_length=0 as unlimited. The extra byte detects an
        # understated original_size, including a falsely declared zero.
        chunk = decompressor.decompress(compressed, original_size + 1)
    except zlib.error as exc:
        raise SaveContainerError(
            f"block {index} zlib stream is corrupt: {exc}"
        ) from exc
    if (
        len(chunk) != original_size
        or decompressor.unconsumed_tail
        or (not decompressor.eof and not compressed.endswith(b"\x00\x00\xff\xff"))
        or decompressor.unused_data
    ):
        raise SaveContainerError(
            f"block {index} decompressed size does not match declared {original_size}"
        )
    return (
        SaveContainerBlock(
            index,
            offset,
            compressed_size,
            original_size,
            checksum,
            True,
            data_offset,
            raw_offset,
            payload[offset:data_offset],
        ),
        chunk,
        data_end,
    )


def _fold_crc16(value: int) -> int:
    return ((value >> 16) ^ (value & 0xFFFF)) & 0xFFFF


def _block_checksum(
    compressed: bytes, compressed_size: int, original_size: int, *, shape: str = "<III"
) -> int:
    header = struct.pack(shape, compressed_size, original_size, 0)
    header_fold = _fold_crc16(zlib.crc32(header) & 0xFFFFFFFF)
    data_fold = _fold_crc16(zlib.crc32(compressed) & 0xFFFFFFFF)
    return (data_fold << 16) | header_fold
