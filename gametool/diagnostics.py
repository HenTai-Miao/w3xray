"""脚本诊断：异步/本地状态/JASS 风险调用的静态提示。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING, Final

from .script_diagnostic_analysis import build_local_state_analysis
from .script_forward_calls import build_forward_call_report

if TYPE_CHECKING:
    from .api import MapData
    from .script_forward_calls import ForwardCallEvidence
    from .script_diagnostic_analysis import DiagnosticCallEvidence


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
    evidence: ForwardCallEvidence | None = None
    calls: tuple[DiagnosticCallEvidence, ...] = ()


@dataclass(frozen=True, slots=True)
class ScriptDiagnosticReport:
    items: tuple[ScriptDiagnostic, ...]

    @property
    def by_code(self) -> dict[str, ScriptDiagnostic]:
        return {item.code: item for item in self.items}

    @property
    def warnings(self) -> tuple[ScriptDiagnostic, ...]:
        return tuple(
            item for item in self.items if item.severity == DiagnosticSeverity.WARNING
        )


@dataclass(frozen=True, slots=True)
class _Rule:
    code: str
    title: str
    detail: str


_RULES: Final = (
    _Rule(
        "script.get_local_player",
        "本地玩家分支",
        "保留 GetLocalPlayer 调用及绑定证据；调用本身不证明形成了本地分支或运行时异步。",
    ),
    _Rule(
        "script.local_state.camera",
        "读取本地相机状态",
        "保留 GetCamera* 调用及绑定证据；本地状态是否参与同步逻辑需要人工确认。",
    ),
    _Rule(
        "script.local_state.mouse",
        "读取本地鼠标状态",
        "保留鼠标 API 名称线索；扩展实现、绑定及同步影响需按原文核对。",
    ),
    _Rule(
        "script.dz_api",
        "Dz API 调用",
        "保留 Dz* 调用名称线索；未假定扩展 API 存在或具有特定运行效果。",
    ),
    _Rule(
        "script.get_local_player.sync_mutation",
        "本地条件内的状态修改调用",
        "GetLocalPlayer 条件控制范围内存在状态修改 API 调用；静态证据不证明该路径执行或必然异步。",
    ),
    _Rule(
        "script.binding.unknown",
        "风险调用绑定未确定",
        "存在风险名称或别名线索，但来源绑定、语言或结构不足以确认原生身份；保留全部证据。",
    ),
    _Rule(
        "script.local_mutation.unknown",
        "本地条件内修改调用未确定",
        "本地条件范围内存在修改名称线索，但绑定或范围未确定；不能据此推断同步状态被修改。",
    ),
    _Rule(
        "script.language.unknown",
        "未知语言的风险调用候选",
        "保留实际调用候选及各语言词法依据；未选择来源语言或推断运行效果。",
    ),
)


def build_script_diagnostics(md: MapData) -> ScriptDiagnosticReport:
    """扫描已解析脚本文本，输出只读诊断提示。"""
    items: list[ScriptDiagnostic] = []
    analysis = build_local_state_analysis(md)
    for rule in _RULES:
        calls = analysis.groups.get(rule.code, ())
        if not calls:
            continue
        items.append(
            ScriptDiagnostic(
                DiagnosticSeverity.WARNING,
                rule.code,
                rule.title,
                rule.detail + "\n" + "\n".join(call.detail for call in calls),
                tuple(sorted({call.source for call in calls})),
                calls=calls,
            )
        )
    for evidence in build_forward_call_report(md).items:
        if evidence.state != "forward" and not (
            evidence.state == "unknown" and evidence.binding != "external"
        ):
            continue
        items.append(
            ScriptDiagnostic(
                DiagnosticSeverity.WARNING,
                f"script.jass.{evidence.state}.{evidence.source}.{evidence.offset}",
                "JASS 直接前向引用"
                if evidence.state == "forward"
                else "JASS 调用绑定未确定",
                f"{evidence.location} · {evidence.form} {evidence.callee} · "
                f"所属函数 {evidence.owner} · 绑定 {evidence.binding} · "
                f"{evidence.diagnostic} · 声明: {'; '.join(evidence.declarations) or '未见'}",
                (evidence.source,),
                evidence,
            )
        )
    return ScriptDiagnosticReport(tuple(items))
