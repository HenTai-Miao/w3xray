r"""共享磁盘缓存根目录解析。

缓存属于派生数据，必须落在仓库外；默认 %LOCALAPPDATA%\w3xray\cache，
可用 W3XRAY_CACHE_DIR 覆盖。所有缓存文件遵守 fail-open：任何读写
异常都回退到现算，绝不影响正确性。
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

__all__ = ("w3xray_cache_root",)


def w3xray_cache_root() -> Path:
    """返回缓存根目录（不负责创建；由写入方按需建子目录）。"""
    override = os.environ.get("W3XRAY_CACHE_DIR")
    if override:
        return Path(override)
    if sys.platform == "win32" and os.environ.get("LOCALAPPDATA"):
        return Path(os.environ["LOCALAPPDATA"]) / "w3xray" / "cache"
    return Path(tempfile.gettempdir()) / "w3xray-cache"
