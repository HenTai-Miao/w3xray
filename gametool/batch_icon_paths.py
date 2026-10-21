"""Collision-safe output paths for physical batch icon files."""

from __future__ import annotations

import hashlib
import os
from pathlib import PurePosixPath

from .safe_output import safe_relative_path


def collision_path(
    root: str,
    name: str,
    payload: bytes,
    *,
    digest: str | None = None,
) -> str:
    """Return a stable hash-suffixed path only for a content collision.

    这里只决定输出文件名；目录/符号链接安全由 write_bytes_safely 的
    双重目的地验证承担，因此存在性检查不再做第三次全路径 realpath
    遍历（图标多的地图一次批处理要多出上千次）。摘要只在真发生
    同尺寸碰撞时才计算，调用方已有原始图标摘要时直接传入。
    """
    relative = safe_relative_path(name)
    if relative is None:
        return name
    destination = os.path.join(root, *relative.parts)
    if not os.path.isfile(destination):
        return name
    if digest is None:
        digest = hashlib.sha256(payload).hexdigest()
    try:
        if os.path.getsize(destination) == len(payload):
            with open(destination, "rb") as handle:
                if hashlib.sha256(handle.read()).hexdigest() == digest:
                    return name
    except OSError:
        return name
    path = PurePosixPath(name.replace("\\", "/"))
    return str(path.with_name(f"{path.stem}_{digest[:8]}{path.suffix}"))


def icon_path_suffix(path: str) -> str:
    """Return a source icon suffix, defaulting extensionless paths to BLP."""
    leaf = path.replace("\\", "/").rsplit("/", 1)[-1]
    return f".{leaf.rsplit('.', 1)[-1]}" if "." in leaf else ".blp"


def without_leaf_suffix(path: str) -> str:
    """Remove only the final path component's suffix."""
    normalized = path.replace("\\", "/")
    leaf = normalized.rsplit("/", 1)[-1]
    return normalized.rsplit(".", 1)[0] if "." in leaf else normalized
