"""Bounded StormLib-compatible MPQ compression dispatch."""

from __future__ import annotations

import bz2
import lzma
import zlib
from collections.abc import Callable
from typing import Final

from .explode import explode
from .mpq_adpcm import MPQADPCMError, decompress_adpcm
from .mpq_constants import (
    COMP_ADPCM_MONO,
    COMP_ADPCM_STEREO,
    COMP_BZIP2,
    COMP_HUFFMAN,
    COMP_PKWARE,
    COMP_SPARSE,
    COMP_ZLIB,
)


MPQ_COMPRESSION_LZMA: Final = 0x12
COMP_LZMA: Final = MPQ_COMPRESSION_LZMA
_LZMA_HEADER_SIZE: Final = 14
_MAX_LZMA_DICTIONARY_SIZE: Final = 64 * 1024 * 1024


class MPQCompressionError(ValueError):
    """Raised for corrupt, unsupported, or over-limit MPQ compression streams."""

    def __init__(self, mask: int, detail: str) -> None:
        self.mask = mask
        self.detail = detail
        super().__init__(f"MPQ compression 0x{mask:02X}: {detail}")


type Decoder = Callable[[bytes, int, int], bytes]


def _bounded_result(mask: int, name: str, result: bytes, output_size: int) -> bytes:
    if len(result) > output_size:
        raise MPQCompressionError(mask, f"{name} decoded output exceeds declared size")
    return result


def _decode_bzip2(data: bytes, output_size: int, mask: int) -> bytes:
    decoder = bz2.BZ2Decompressor()
    try:
        result = decoder.decompress(data, max_length=output_size + 1)
    except OSError as error:
        raise MPQCompressionError(mask, f"corrupt bzip2 stream: {error}") from error
    if len(result) > output_size:
        return result[:output_size]
    if not decoder.eof:
        raise MPQCompressionError(mask, "truncated bzip2 stream")
    if decoder.unused_data:
        raise MPQCompressionError(mask, "trailing bzip2 data")
    return result


def _decode_pkware(data: bytes, output_size: int, mask: int) -> bytes:
    try:
        result = explode(data, max_output=output_size + 1)
    except ValueError as error:
        raise MPQCompressionError(mask, f"corrupt PKWARE stream: {error}") from error
    return _bounded_result(mask, "PKWARE", result, output_size)


def _decode_zlib(data: bytes, output_size: int, mask: int) -> bytes:
    decoder = zlib.decompressobj()
    try:
        result = decoder.decompress(data, output_size + 1)
    except zlib.error as error:
        raise MPQCompressionError(mask, f"corrupt zlib stream: {error}") from error
    if len(result) > output_size:
        return result[:output_size]
    if not decoder.eof:
        raise MPQCompressionError(mask, "truncated zlib stream")
    if decoder.unused_data or decoder.unconsumed_tail:
        raise MPQCompressionError(mask, "trailing zlib data")
    return result


def _decode_huffman(data: bytes, output_size: int, mask: int) -> bytes:
    from . import mpq as mpq_facade

    try:
        result = mpq_facade.huff_decompress(data, output_size + 1)
    except (IndexError, ValueError) as error:
        raise MPQCompressionError(mask, f"corrupt Huffman stream: {error}") from error
    return _bounded_result(mask, "Huffman", result, output_size)


def _decode_adpcm_stereo(data: bytes, output_size: int, mask: int) -> bytes:
    try:
        return decompress_adpcm(data, channels=2, output_size=output_size)
    except MPQADPCMError as error:
        raise MPQCompressionError(mask, f"ADPCM stereo: {error}") from error


def _decode_adpcm_mono(data: bytes, output_size: int, mask: int) -> bytes:
    try:
        return decompress_adpcm(data, channels=1, output_size=output_size)
    except MPQADPCMError as error:
        raise MPQCompressionError(mask, f"ADPCM mono: {error}") from error


def _decode_sparse(data: bytes, output_size: int, mask: int) -> bytes:
    if len(data) < 5:
        raise MPQCompressionError(mask, "truncated sparse stream")
    declared = int.from_bytes(data[:4], "big")
    if declared > output_size:
        raise MPQCompressionError(mask, "sparse decoded output exceeds declared size")
    out = bytearray()
    position = 4
    while position < len(data) and len(out) < declared:
        control = data[position]
        position += 1
        remaining = declared - len(out)
        if control & 0x80:
            count = min((control & 0x7F) + 1, remaining)
            if position + count > len(data):
                raise MPQCompressionError(mask, "truncated sparse literal chunk")
            out.extend(data[position : position + count])
            position += count
        else:
            out.extend(b"\x00" * min((control & 0x7F) + 3, remaining))
    if len(out) != declared:
        raise MPQCompressionError(mask, "truncated sparse output")
    return bytes(out)


_STORMLIB_REVERSE_ORDER: Final[tuple[tuple[int, Decoder], ...]] = (
    (COMP_BZIP2, _decode_bzip2),
    (COMP_PKWARE, _decode_pkware),
    (COMP_ZLIB, _decode_zlib),
    (COMP_HUFFMAN, _decode_huffman),
    (COMP_ADPCM_STEREO, _decode_adpcm_stereo),
    (COMP_ADPCM_MONO, _decode_adpcm_mono),
    (COMP_SPARSE, _decode_sparse),
)


def _decode_lzma(data: bytes, output_size: int, mask: int) -> bytes:
    if len(data) <= _LZMA_HEADER_SIZE:
        raise MPQCompressionError(mask, "truncated LZMA header or stream")
    if data[0] != 0:
        raise MPQCompressionError(mask, "unsupported LZMA filter")
    prop = data[1]
    if prop >= 9 * 5 * 5:
        raise MPQCompressionError(mask, "invalid LZMA properties")
    dictionary_size = int.from_bytes(data[2:6], "little")
    if dictionary_size > _MAX_LZMA_DICTIONARY_SIZE:
        raise MPQCompressionError(mask, "LZMA dictionary exceeds safe limit")
    declared = int.from_bytes(data[6:14], "little")
    if declared > output_size:
        raise MPQCompressionError(mask, "LZMA declared size exceeds output contract")
    remainder, lc = divmod(prop, 9)
    pb, lp = divmod(remainder, 5)
    filters = [{
        "id": lzma.FILTER_LZMA1,
        "dict_size": max(4096, dictionary_size),
        "lc": lc,
        "lp": lp,
        "pb": pb,
    }]
    try:
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_RAW, filters=filters)
        result = decoder.decompress(data[_LZMA_HEADER_SIZE:], max_length=declared + 1)
    except lzma.LZMAError as error:
        raise MPQCompressionError(
            mask, f"corrupt or truncated LZMA stream: {error}"
        ) from error
    if len(result) > declared:
        raise MPQCompressionError(
            mask, "LZMA decoded size exceeds declaration (trailing data)"
        )
    if not decoder.eof:
        result = _validate_lzma_alone(data, declared, mask)
    if decoder.unused_data:
        raise MPQCompressionError(mask, "trailing LZMA data")
    if len(result) != declared:
        raise MPQCompressionError(mask, "LZMA decoded size does not match declaration")
    return result


def _validate_lzma_alone(data: bytes, declared: int, mask: int) -> bytes:
    """Validate known-size StormLib streams that legitimately omit an end marker."""
    try:
        decoder = lzma.LZMADecompressor(format=lzma.FORMAT_ALONE)
        result = decoder.decompress(data[1:], max_length=declared + 1)
    except lzma.LZMAError as error:
        raise MPQCompressionError(mask, f"truncated LZMA stream: {error}") from error
    if not decoder.eof:
        raise MPQCompressionError(mask, "truncated LZMA stream")
    if decoder.unused_data:
        raise MPQCompressionError(mask, "trailing LZMA data")
    if len(result) != declared:
        raise MPQCompressionError(mask, "LZMA decoded size does not match declaration")
    return result


def sparse_decompress(data: bytes, max_output: int | None = None) -> bytes:
    """Compatibility entry point for the historical sparse helper."""
    output_size = 0xFFFFFFFF if max_output is None else max(0, max_output)
    return _decode_sparse(data, output_size, COMP_SPARSE)


def decompress_mpq_sector(data: bytes, output_size: int) -> bytes:
    """Decode one MPQ compressed sector in StormLib's reverse method order."""
    marker = data[0] if data else 0
    if output_size < 0:
        raise MPQCompressionError(marker, f"invalid output size: {output_size}")
    if not data:
        return b""
    payload = data[1:]
    if marker == MPQ_COMPRESSION_LZMA:
        return _decode_lzma(payload, output_size, marker)
    if marker & COMP_ADPCM_MONO and marker & COMP_ADPCM_STEREO:
        raise MPQCompressionError(marker, "mono and stereo ADPCM flags are mutually exclusive")
    remaining = marker
    for flag, decoder in _STORMLIB_REVERSE_ORDER:
        if remaining & flag:
            payload = decoder(payload, output_size, marker)
            remaining &= ~flag
    if remaining:
        raise MPQCompressionError(marker, f"unsupported bits 0x{remaining:02X}")
    return _bounded_result(marker, "chain", payload, output_size)
