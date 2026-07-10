from __future__ import annotations

import struct

import pytest

from w3xtool.mpq_adpcm import MPQADPCMError, decompress_adpcm
from w3xtool.mpq_compression import MPQCompressionError, decompress_mpq_sector


def _samples(data: bytes) -> tuple[int, ...]:
    return struct.unpack(f"<{len(data) // 2}h", data)


def test_mono_predictor_and_step_markers_match_stormlib() -> None:
    encoded = b"\x00\x00" + struct.pack("<h", 1000) + b"\x00\x40\x80\x81\x01"

    actual = decompress_adpcm(encoded, channels=1, output_size=10)

    assert _samples(actual) == (1000, 1494, 1045, 1045, 2637)


def test_stereo_channel_rotation_matches_stormlib() -> None:
    encoded = b"\x00\x01" + struct.pack("<2h", 1000, -1000) + b"\x00\x00\x81\x40"

    actual = decompress_adpcm(encoded, channels=2, output_size=10)

    assert _samples(actual) == (1000, -1000, 1247, -753, 766)


@pytest.mark.parametrize("channels", (0, 3))
def test_invalid_channel_count_is_rejected(channels: int) -> None:
    with pytest.raises(MPQADPCMError, match="channels"):
        decompress_adpcm(b"\x00\x00\x00\x00", channels=channels, output_size=16)


@pytest.mark.parametrize("encoded", (b"", b"\x00", b"\x00\x00", b"\x00\x00\x01"))
def test_truncated_mono_header_is_rejected(encoded: bytes) -> None:
    with pytest.raises(MPQADPCMError, match="header"):
        decompress_adpcm(encoded, channels=1, output_size=16)


def test_output_overflow_is_rejected_without_partial_success() -> None:
    encoded = b"\x00\x00" + struct.pack("<h", 1000) + b"\x00"

    with pytest.raises(MPQADPCMError, match="output"):
        decompress_adpcm(encoded, channels=1, output_size=2)


def test_dispatch_wraps_adpcm_failure_as_compression_error() -> None:
    with pytest.raises(MPQCompressionError, match="ADPCM mono"):
        decompress_mpq_sector(b"\x40\x00", 16)


def test_repeated_calls_do_not_reuse_predictor_state() -> None:
    encoded = b"\x00\x00" + struct.pack("<h", -200) + b"\x01\x01"

    first = decompress_adpcm(encoded, channels=1, output_size=6)
    second = decompress_adpcm(encoded, channels=1, output_size=6)

    assert first == second
