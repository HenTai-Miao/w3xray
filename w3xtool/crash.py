"""已知魔兽地图崩溃模式的只读静态检测。"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .api import GameObject, MapData


@dataclass(frozen=True, slots=True)
class CrashRisk:
    code: str
    title: str
    detail: str
    object_id: str = ""
    object_name: str = ""
    source: str = ""


@dataclass(frozen=True, slots=True)
class CrashReport:
    items: tuple[CrashRisk, ...]

    @property
    def by_code(self) -> dict[str, CrashRisk]:
        return {item.code: item for item in self.items}


def build_crash_report(md: MapData) -> CrashReport:
    """扫描对象数据中已知的崩溃风险配置。"""
    items: list[CrashRisk] = []
    for obj in _all_objects(md):
        risk = _chain_lightning_decay_risk(obj)
        if risk is not None:
            items.append(risk)
    items.extend(_game_cache_script_risks(md))
    return CrashReport(tuple(items))


def _all_objects(md: MapData) -> list[GameObject]:
    return [obj for group in md.objects.values() for obj in group]


def _chain_lightning_decay_risk(obj: GameObject) -> CrashRisk | None:
    if not _is_chain_lightning(obj):
        return None
    for label, value in obj.fields:
        if "每个目标伤害减少" not in str(label):
            continue
        parsed = _parse_real(str(value))
        if parsed is not None and parsed <= -1.0:
            return CrashRisk(
                code="crash.chain_lightning.full_negative_decay",
                title="闪电链 -100% 衰减",
                detail=(
                    "1.24E~1.26 已知风险：闪电链每个目标伤害减少为 -100% "
                    "或更低时可能触发崩溃/退出报错。"
                ),
                object_id=obj.obj_id,
                object_name=obj.name,
                source=f"对象 {obj.obj_id}",
            )
    return None


def _is_chain_lightning(obj: GameObject) -> bool:
    text = f"{obj.obj_id} {obj.base_id} {obj.name}".lower()
    return "aocl" in text or "accl" in text or "aicl" in text or "闪电链" in text


def _parse_real(value: str) -> float | None:
    cleaned = value.strip().replace("%", "")
    if not cleaned:
        return None
    try:
        number = float(cleaned)
    except ValueError:
        return None
    if "%" in value:
        return number / 100.0
    return number


_GAME_CACHE_RE = re.compile(
    r"\b(?:InitGameCache|SaveGameCache|Store(?:Integer|Real|Boolean|String|Unit)|"
    r"SyncStored(?:Integer|Real|Boolean|String|Unit)|FlushGameCache|"
    r"ReloadGameCachesFromDisk)\s*\(",
    re.IGNORECASE,
)


def _game_cache_script_risks(md: MapData) -> tuple[CrashRisk, ...]:
    out: list[CrashRisk] = []
    for script_name, text in sorted(md.scripts.items()):
        if not _GAME_CACHE_RE.search(text):
            continue
        out.append(CrashRisk(
            code="crash.game_cache.api",
            title="游戏缓存 API",
            detail=(
                "崩溃案例中包含旧版游戏缓存存储相关问题；发现 InitGameCache/"
                "Store*/SaveGameCache 等调用，建议检查 MissionKey/缓存写入逻辑和目标版本。"
            ),
            source=f"脚本 {script_name}",
        ))
    return tuple(out)
