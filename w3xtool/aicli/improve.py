"""AI 自改进编排：诊断 → 组装提示 → 调 AI → 存建议（开发期）/ 返回标注（运行时）。

开发期(attribute)：把 AI 产出存到 ai_suggestions/<图名>/，由人工审阅后应用，不自动改代码。
运行时(annotate)：只返回 AI 的解释文本，供 GUI 面板展示，不落地任何改动。
"""
from __future__ import annotations

import os
import re

from ..audit import audit_map, report_text
from .runner import AIProfile, run_ai

# 提示词目录：项目根下的 prompts/
_PROMPTS_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "prompts")


def load_prompt(name: str, prompts_dir: str | None = None) -> str:
    path = os.path.join(prompts_dir or _PROMPTS_DIR, name + ".md")
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def build_prompt(template_text: str, diag) -> str:
    """把诊断报告注入提示词模板的 {report} 占位。"""
    return template_text.replace("{report}", report_text(diag))


def _safe_name(name: str) -> str:
    return re.sub(r'[\\/:*?"<>|]+', "_", name).strip() or "map"


def save_suggestion(out_root: str, map_name: str, report: str, ai_result) -> str:
    """把诊断报告 + AI 产出存到 out_root/<图名>/，返回该目录。"""
    folder = os.path.join(out_root, _safe_name(map_name))
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, "diagnostic.md"), "w", encoding="utf-8") as f:
        f.write(report)
    body = ai_result.stdout if ai_result.ok else "(AI 调用失败：%s)\n\n%s" % (
        ai_result.error, ai_result.stderr)
    with open(os.path.join(folder, "ai_suggestion.md"), "w", encoding="utf-8") as f:
        f.write(body or "(无输出)")
    return folder


def attribute(diag, profile: AIProfile, prompts_dir: str | None = None,
              out_root: str = "ai_suggestions"):
    """开发期：让 AI 对诊断归因+提修复，结果存档供人工审阅。返回 (目录, AIResult)。"""
    template = load_prompt("attribution", prompts_dir)
    prompt = build_prompt(template, diag)
    result = run_ai(profile, prompt)
    folder = save_suggestion(out_root, diag.name, report_text(diag), result)
    return folder, result


def annotate(diag, profile: AIProfile, prompts_dir: str | None = None) -> str:
    """运行时：让 AI 解释/标注异常，返回纯文本（不落地任何改动）。"""
    template = load_prompt("annotate", prompts_dir)
    prompt = build_prompt(template, diag)
    result = run_ai(profile, prompt)
    if result.ok:
        return result.stdout
    return "(AI 调用失败：%s)" % result.error


def run_attribution(map_path: str, profile: AIProfile, prompts_dir: str | None = None,
                    out_root: str = "ai_suggestions"):
    """开发期入口：审计一张图 → AI 归因 → 存建议。"""
    diag = audit_map(map_path)
    return attribute(diag, profile, prompts_dir, out_root)


def run_annotation(map_path: str, profile: AIProfile, prompts_dir: str | None = None) -> str:
    """运行时入口：审计一张图 → AI 标注 → 返回文本。"""
    diag = audit_map(map_path)
    return annotate(diag, profile, prompts_dir)
