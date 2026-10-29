"""Lossless save-text decoding with an explicit boundary for BOMless UTF-16."""

from __future__ import annotations

from dataclasses import dataclass


SAVE_TEXT_ENCODINGS = ("auto", "utf-8", "gb18030", "utf-16-le", "utf-16-be")
_BOMS = (
    (b"\xef\xbb\xbf", "utf-8"),
    (b"\xff\xfe", "utf-16-le"),
    (b"\xfe\xff", "utf-16-be"),
)


def normalize_save_text_encoding(value: str) -> str:
    """Accept common codec spellings, but never arbitrary or lossy codecs."""
    if not isinstance(value, str):
        raise ValueError("存档文本编码必须是字符串")
    normalized = value.strip().lower().replace("_", "-")
    normalized = {
        "utf8": "utf-8",
        "utf-16le": "utf-16-le",
        "utf16le": "utf-16-le",
        "utf-16be": "utf-16-be",
        "utf16be": "utf-16-be",
    }.get(normalized, normalized)
    if normalized not in SAVE_TEXT_ENCODINGS:
        raise ValueError(
            f"不支持的存档文本编码：{value}；请选择 " + ", ".join(SAVE_TEXT_ENCODINGS)
        )
    return normalized


@dataclass(frozen=True, slots=True)
class SaveTextDecoding:
    text: str | None
    encoding: str
    bom_bytes: int
    requested_encoding: str
    diagnostics: tuple[str, ...] = ()

    def to_dict(self, payload: bytes) -> dict[str, object]:
        return {
            "requested_encoding": self.requested_encoding,
            "selection": "automatic"
            if self.requested_encoding == "auto"
            else "explicit",
            "encoding": self.encoding,
            "bom_bytes": self.bom_bytes,
            "bom_hex": payload[: self.bom_bytes].hex(),
            "byte_roundtrip": self.text is not None,
            "diagnostics": list(self.diagnostics),
        }


def _strict_text(
    payload: bytes, encoding: str, bom_bytes: int, requested: str
) -> SaveTextDecoding:
    body = payload[bom_bytes:]
    try:
        text = body.decode(encoding, errors="strict")
    except UnicodeDecodeError as exc:
        return SaveTextDecoding(
            None,
            encoding,
            bom_bytes,
            requested,
            (
                f"{encoding} 严格解码失败：源字节 {bom_bytes + exc.start}:{bom_bytes + exc.end} ({exc.reason})；完整原始字节已保留。",
            ),
        )
    if text.encode(encoding, errors="strict") != body:
        return SaveTextDecoding(
            None,
            encoding,
            bom_bytes,
            requested,
            (
                f"{encoding} 解码后重新编码与源字节不一致；未交付猜测文本，完整原始字节已保留。",
            ),
        )
    for index, char in enumerate(text):
        point = ord(char)
        if point < 9 or 13 < point < 32:
            return SaveTextDecoding(
                None,
                encoding,
                bom_bytes,
                requested,
                (
                    f"{encoding} 文本在字符 {index} 含控制字符 U+{point:04X}；未将二进制控制数据当作文本，完整原始字节已保留。",
                ),
            )
    return SaveTextDecoding(text, encoding, bom_bytes, requested)


def inspect_save_text(payload: bytes, text_encoding: str = "auto") -> SaveTextDecoding:
    """Decode complete bytes, never infer BOMless UTF-16 from NUL distribution.

    An explicit endian choice states the caller's interpretation. Round-trip
    validation proves byte coverage, not that the chosen encoding is semantic
    evidence for a map or runtime state.
    """
    requested = normalize_save_text_encoding(text_encoding)
    if payload.startswith((b"\xff\xfe\x00\x00", b"\x00\x00\xfe\xff")):
        return SaveTextDecoding(
            None,
            "",
            4,
            requested,
            (
                "来源带 UTF-32 BOM；此文本编码尚未支持，未按 UTF-16 猜测，完整原始字节已保留。",
            ),
        )
    for marker, encoding in _BOMS:
        if payload.startswith(marker):
            if requested not in ("auto", encoding):
                return SaveTextDecoding(
                    None,
                    encoding,
                    len(marker),
                    requested,
                    (
                        f"指定编码 {requested} 与来源 BOM {encoding} 冲突；请核对编码后重试，完整原始字节已保留。",
                    ),
                )
            return _strict_text(payload, encoding, len(marker), requested)
    if requested != "auto":
        return _strict_text(payload, requested, 0, requested)
    if any(byte < 9 or 13 < byte < 32 for byte in payload):
        return SaveTextDecoding(
            None,
            "",
            0,
            requested,
            (
                "未识别完整文本编码：来源无 BOM 且含 NUL 或二进制控制字节；auto 不猜测 UTF-16。若已知来源为 UTF-16 文本，请明确选择 utf-16-le 或 utf-16-be 后重试；完整原始字节已保留。",
            ),
        )
    diagnostics: list[str] = []
    for encoding in ("utf-8", "gb18030"):
        result = _strict_text(payload, encoding, 0, requested)
        if result.text is not None:
            return result
        diagnostics.extend(result.diagnostics)
    return SaveTextDecoding(
        None,
        "",
        0,
        requested,
        (
            "未识别完整文本编码；可明确选择已知编码后重试，未替换或丢失源字节。",
            *diagnostics,
        ),
    )
