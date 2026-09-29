"""Shared symlink-capability probe for security-boundary tests.

无特权 Windows（WinError 1314）上创建符号链接会失败；依赖真实符号链接的
用例按能力跳过，让本机套件保持全绿（红色只留真回归）。
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest


def _probe() -> bool:
    with tempfile.TemporaryDirectory() as tmp:
        target = Path(tmp, "target.txt")
        target.write_text("x", encoding="utf-8")
        try:
            os.symlink(target, Path(tmp, "link.txt"))
        except OSError, NotImplementedError:
            return False
        return True


SYMLINKS_SUPPORTED: bool = _probe()

skip_if_symlinks_unsupported = pytest.mark.skipif(
    not SYMLINKS_SUPPORTED,
    reason="os.symlink 不可用（Windows 无特权 WinError 1314）",
)
