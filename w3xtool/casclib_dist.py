"""Windows distribution validation for locally built CascLib artifacts."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import platform
from pathlib import Path
from typing import Final, override

_DLL_RELATIVE: Final = Path("third_party/CascLib/bin/win-x64/CascLib.dll")
_HASH_RELATIVE: Final = Path("third_party/CascLib/bin/win-x64/CascLib.dll.sha256")
_AMD64_MACHINE: Final = 0x8664


@dataclass(frozen=True, slots=True)
class CascLibDistError(RuntimeError):
    path: Path
    reason: str

    @override
    def __str__(self) -> str:
        return f"CascLib Windows 打包校验失败：{self.reason}：{self.path}"


def validate_casclib_dist_assets(project_root: Path, *, system: str | None = None) -> None:
    """Require a matching SHA256 and x64 PE DLL for Windows builds only."""
    current_system = system or platform.system()
    if current_system != "Windows":
        return
    dll_path = project_root / _DLL_RELATIVE
    hash_path = project_root / _HASH_RELATIVE
    if not dll_path.is_file():
        raise CascLibDistError(path=dll_path, reason="缺少 CascLib.dll")
    if not hash_path.is_file():
        raise CascLibDistError(path=hash_path, reason="缺少 CascLib.dll.sha256")
    expected = hash_path.read_text(encoding="ascii").strip().lower()
    actual = hashlib.sha256(dll_path.read_bytes()).hexdigest()
    if expected != actual:
        raise CascLibDistError(path=dll_path, reason="SHA256 不匹配")
    if not _is_x64_pe(dll_path):
        raise CascLibDistError(path=dll_path, reason="不是 x64 PE")


def _is_x64_pe(path: Path) -> bool:
    data = path.read_bytes()
    if len(data) < 64 or data[:2] != b"MZ":
        return False
    pe_offset = int.from_bytes(data[0x3C:0x40], "little")
    header_end = pe_offset + 6
    if header_end > len(data) or data[pe_offset:pe_offset + 4] != b"PE\0\0":
        return False
    machine = int.from_bytes(data[pe_offset + 4:header_end], "little")
    return machine == _AMD64_MACHINE
