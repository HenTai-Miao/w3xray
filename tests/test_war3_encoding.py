"""Cross-locale Warcraft legacy text decoding contracts."""

from __future__ import annotations

from unittest.mock import patch

from w3xtool.war3_encoding import decode_warcraft_string, default_legacy_codecs


def test_single_byte_windows_acp_does_not_mask_gbk_text() -> None:
    # Given: an English Windows locale and a Chinese legacy map string.
    raw = "测试".encode("gbk")

    # When: the default legacy codec order is built for cp1252.
    with patch("w3xtool.war3_encoding.locale.getpreferredencoding", return_value="cp1252"):
        decoded = decode_warcraft_string(raw)

    # Then: the permissive single-byte ACP cannot preempt a valid GBK decode.
    assert decoded == "测试"


def test_multibyte_windows_acp_remains_ahead_of_gbk() -> None:
    # Given: a Traditional Chinese Windows locale whose bytes differ from GBK.
    raw = "測試".encode("cp950")

    # When: the default codec order is built for cp950.
    with patch("w3xtool.war3_encoding.locale.getpreferredencoding", return_value="cp950"):
        codecs = default_legacy_codecs()
        decoded = decode_warcraft_string(raw)

    # Then: the active multibyte ACP remains authoritative.
    assert codecs[0] == "cp950"
    assert decoded == "測試"
