"""攻略速查报告的按图磁盘缓存：同一地图版本重复查询零解析。

缓存键 = 工具版本标签 + 地图路径 + 大小 + mtime，地图被编辑器改动
即失效。遵守 fail-open：任何异常都当作未命中。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path

from .cache_root import w3xray_cache_root

__all__ = (
    "report_cache_path",
    "load_cached_report",
    "store_cached_report",
)

# 报告段落逻辑变化时同步 bump，使旧缓存整体失效。
GUIDE_CACHE_VERSION = "guide-v1"


def report_cache_path(map_path: str) -> Path | None:
    """按地图文件身份（路径+大小+mtime）派生缓存文件路径。"""
    if os.environ.get("W3XRAY_GUIDE_CACHE", "1") != "1":
        return None
    try:
        stat = os.stat(map_path)
        resolved = os.path.abspath(map_path)
    except OSError:
        return None
    digest = hashlib.sha256(
        f"{GUIDE_CACHE_VERSION}|{resolved}|{stat.st_size}|{stat.st_mtime_ns}".encode()
    )
    return w3xray_cache_root() / "guide-reports" / f"{digest.hexdigest()}.txt"


def load_cached_report(path: Path | None) -> str | None:
    """命中返回缓存报告文本；缺失/损坏返回 None。"""
    if path is None:
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError, UnicodeDecodeError:
        return None


def store_cached_report(path: Path | None, text: str) -> None:
    """尽力写入（原子替换）；失败静默。"""
    if path is None:
        return
    temp_name: str | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle, temp_name = tempfile.mkstemp(
            dir=str(path.parent), prefix=path.name, suffix=".tmp"
        )
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as temp_file:
            temp_file.write(text)
        os.replace(temp_name, path)
    except OSError:
        if temp_name is not None:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
