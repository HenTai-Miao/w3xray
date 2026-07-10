"""脚本诊断：异步/本地状态/JASS 风险调用的静态提示。"""
from __future__ import annotations

from collections.abc import Mapping
import re
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .script_sources import analysis_script_texts

if TYPE_CHECKING:
    from .api import MapData


class DiagnosticSeverity(StrEnum):
    INFO = "info"
    WARNING = "warning"


@dataclass(frozen=True, slots=True)
class ScriptDiagnostic:
    severity: DiagnosticSeverity
    code: str
    title: str
    detail: str
    scripts: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ScriptDiagnosticReport:
    items: tuple[ScriptDiagnostic, ...]

    @property
    def by_code(self) -> dict[str, ScriptDiagnostic]:
        return {item.code: item for item in self.items}

    @property
    def warnings(self) -> tuple[ScriptDiagnostic, ...]:
        return tuple(item for item in self.items if item.severity == DiagnosticSeverity.WARNING)


@dataclass(frozen=True, slots=True)
class _Rule:
    code: str
    title: str
    detail: str
    pattern: re.Pattern[str]


_RULES: Final = (
    _Rule(
        "script.get_local_player",
        "本地玩家分支",
        "发现 GetLocalPlayer；若在本地分支中修改同步状态，可能导致异步/掉线。",
        re.compile(r"\bGetLocalPlayer\s*\(", re.IGNORECASE),
    ),
    _Rule(
        "script.local_state.camera",
        "读取本地相机状态",
        "发现 GetCamera* 调用；相机状态属于本地客户端信息，参与同步逻辑时需要人工确认。",
        re.compile(r"\bGetCamera[A-Za-z0-9_]*\s*\(", re.IGNORECASE),
    ),
    _Rule(
        "script.local_state.mouse",
        "读取本地鼠标状态",
        "发现鼠标位置/事件相关调用；鼠标状态通常是本地输入，参与同步逻辑时需要人工确认。",
        re.compile(r"\b(?:DzGetMouse|DzTriggerRegisterMouse)[A-Za-z0-9_]*\s*\(", re.IGNORECASE),
    ),
    _Rule(
        "script.dz_api",
        "Dz API 调用",
        "发现 Dz* 调用；这类扩展 API 常和平台/本地状态相关，跨版本或联机同步需人工确认。",
        re.compile(r"\bDz[A-Za-z0-9_]*\s*\(", re.IGNORECASE),
    ),
)
_LOCAL_BRANCH_RE: Final = re.compile(r"\bGetLocalPlayer\s*\(", re.IGNORECASE)
_LOCAL_BRANCH_END_RE: Final = re.compile(r"\b(?:endif|end)\b", re.IGNORECASE)
_SYNC_MUTATION_RE: Final = re.compile(
    r"\b(?:CreateUnit|CreateItem|CreateDestructable|KillUnit|RemoveUnit|RemoveItem|"
    r"RemoveDestructable|SetUnit[A-Za-z0-9_]*|SetHero[A-Za-z0-9_]*|"
    r"SetWidgetLife|SetPlayerState|SetPlayerTechResearched|SetResourceAmount|"
    r"SetItem[A-Za-z0-9_]*|SetDestructable[A-Za-z0-9_]*|"
    r"UnitAddAbility|UnitRemoveAbility)\s*\(",
    re.IGNORECASE,
)


def build_script_diagnostics(md: MapData) -> ScriptDiagnosticReport:
    """扫描已解析脚本文本，输出只读诊断提示。"""
    items: list[ScriptDiagnostic] = []
    analysis_scripts = dict(analysis_script_texts(md))
    for rule in _RULES:
        matched_scripts = tuple(
            name for name, text in sorted(analysis_scripts.items())
            if text and rule.pattern.search(text)
        )
        if not matched_scripts:
            continue
        items.append(ScriptDiagnostic(
            DiagnosticSeverity.WARNING,
            rule.code,
            rule.title,
            rule.detail,
            matched_scripts,
        ))
    mutation_scripts = _scripts_with_local_sync_mutations(analysis_scripts)
    if mutation_scripts:
        items.append(ScriptDiagnostic(
            DiagnosticSeverity.WARNING,
            "script.get_local_player.sync_mutation",
            "本地分支修改同步状态",
            "发现 GetLocalPlayer 分支内调用 CreateUnit/SetUnit*/SetPlayerState 等同步状态修改函数，"
            "这类写法通常会导致联机异步或掉线。",
            mutation_scripts,
        ))
    return ScriptDiagnosticReport(tuple(items))


def _scripts_with_local_sync_mutations(scripts: Mapping[str, str]) -> tuple[str, ...]:
    return tuple(
        name for name, text in sorted(scripts.items())
        if text and _has_local_sync_mutation(text)
    )


def _has_local_sync_mutation(text: str) -> bool:
    in_local_branch = False
    for line in text.splitlines():
        if _LOCAL_BRANCH_RE.search(line):
            in_local_branch = True
        if in_local_branch and _SYNC_MUTATION_RE.search(line):
            return True
        if in_local_branch and _LOCAL_BRANCH_END_RE.search(line):
            in_local_branch = False
    return False
