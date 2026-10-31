"""攻略速查报告的按图磁盘缓存：同一地图版本重复查询零解析。

缓存键包含工具版本、地图路径与完整源字节 SHA-256；读取和交付边界
重新验证来源。缓存 I/O 遵守 fail-open，已加载来源变化必须明确失败。
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from .archive_source import BytesArchiveSource
from .bounded_file import sha256_regular_file
from .cache_root import gamexray_cache_root

if TYPE_CHECKING:
    from .map_data import MapData

__all__ = (
    "load_cached_report",
    "report_cache_path",
    "store_cached_report",
    "verify_loaded_guide_source",
)

# 报告段落逻辑变化时同步 bump，使旧缓存整体失效。
# v2: 满量纪律后的报告语义 (配方证据标注/全文 tooltip/无条数上限)——
# 代码修复救不了旧缓存, 版本换代让旧报告立刻退役。
# v3: drops 段并入脚本死亡触发证据 (直落掷骰/奖池 N选1, 与 pack-query
# drop 同源正则)——旧 v2 报告的掉落段缺此类证据, 整体退役。
# v4: 新增「开箱与随机产出」段 (使用触发数组池, 与 where 同源)——旧 v3
# 报告缺该段落, 整体退役。
# v5: loot 段扩为「开箱与兑换产出」(并入拾取触发的直接发放/掷骰门槛)——
# 旧 v4 报告缺拾取维度证据, 整体退役。
# v6: drops 段并入「可破坏物掉落」关系 (箱子/路障, 旧 v5 只读单位掉落)——
# 旧 v5 报告缺该维度, 整体退役。
# v7: 战役容器 (.w3n) 报告尾附逐关查询指引 (旧 v6 容器报告无解释)——
# 旧 v6 整体退役。
# v8: 容器 --section 空段改为输出同一指引 (旧 v7 空段什么都不印)——旧 v7 退役。
GUIDE_CACHE_VERSION = "guide-v43"  # v43: 完整对象证据与脚本解析语义修复


def report_cache_path(map_path: str) -> Path | None:
    """Derive the key from one complete, stable source-byte fingerprint."""
    if os.environ.get("GAMEXRAY_GUIDE_CACHE", "1") != "1":
        return None
    try:
        source_hash, _identity = sha256_regular_file(Path(map_path))
        resolved = os.path.abspath(map_path)
    except OSError:
        return None
    digest = hashlib.sha256(
        f"{GUIDE_CACHE_VERSION}|sha256|{resolved}|{source_hash}".encode()
    )
    return gamexray_cache_root() / "guide-reports" / f"{digest.hexdigest()}.txt"


def verify_loaded_guide_source(md: MapData) -> None:
    """Keep retained map evidence bound to its original bytes before reporting."""
    source = md.archive_source
    if source is None:
        # Explicit in-memory MapData has no external path identity to certify.
        return
    if isinstance(source, BytesArchiveSource):
        # Campaign members are immutable owned bytes, not filesystem paths.
        if source.is_closed:
            raise OSError("攻略来源快照已关闭，请重新打开地图")
        return
    ledger = md.extraction_ledger
    if ledger is None:
        raise OSError("攻略来源缺少加载时的完整字节指纹，请重新打开地图")
    with source.open():
        current_hash, _identity = sha256_regular_file(Path(source.path))
    if current_hash != ledger.source_sha256:
        raise OSError("地图来源字节已变化，当前已加载内容属于旧快照；请重新打开地图")


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
