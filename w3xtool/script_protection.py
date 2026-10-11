"""平台插件加密脚本块签名检测（只读静态证据）。

真实地图案例：KK 平台地图把全部触发脚本加密为无名 MPQ 块
（文件头 "KKWE PLUG-IN ENCRYPT JASS!"），war3map.j 只剩 5 行存根；
静态管线此时会给出"主脚本已解析"的误导结论。本模块提供签名
嗅探与证据输出，挂在无名块导出循环里零额外 IO。
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

ENCRYPTED_SCRIPT_SIGNATURES: Final[tuple[tuple[str, bytes], ...]] = (
    ("KKWE 加密 JASS", b"KKWE PLUG-IN ENCRYPT JASS!"),
)
_SNIFF_HEAD_BYTES: Final = 64


@dataclass(frozen=True, slots=True)
class EncryptedScriptDetection:
    """One anonymous block whose payload carries an encrypted-script signature."""

    block_index: int
    kind: str
    label: str
    size: int


def detect_encrypted_script_label(data: bytes) -> str | None:
    """Return the signature label when the ``data`` head carries a known marker."""
    head = bytes(data[:_SNIFF_HEAD_BYTES])
    for label, signature in ENCRYPTED_SCRIPT_SIGNATURES:
        if signature in head:
            return label
    return None


def format_encrypted_script_report(
    detections: Sequence[EncryptedScriptDetection],
) -> str:
    """Format user-facing evidence lines for encrypted script blocks."""
    lines = ["检测到平台插件加密脚本块："]
    lines.extend(
        f"- 块 {d.block_index:06d}（{d.kind}，{d.size} 字节）：{d.label}"
        for d in detections
    )
    lines.extend(
        (
            "",
            "真实脚本被加密存放，静态解析读不到触发逻辑；",
            "隐藏指令、合成、掉落触发等脚本类分析对这类地图不可用。",
            "本工具只做静态签名检测，不做运行时解密或绕过。",
        )
    )
    return "\n".join(lines) + "\n"
