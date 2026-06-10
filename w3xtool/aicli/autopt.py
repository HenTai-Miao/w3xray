"""AI 全自动优化解析逻辑：AI 直接产出修改 → 自动应用 → 测试门禁 → 提交/回滚。

与 improve.attribute（AI 提补丁、人工应用）不同，这里全自动：
  AI 输出统一 diff → git apply → 跑全套测试 → 全过则 commit(+push)，否则回滚到改前。
测试门禁 + 失败回滚是唯一也是足够的安全网：坏改动绝不进仓库。

安全前提：运行前要求工作区干净（保护用户未提交的改动）；失败时
`git reset --hard HEAD` + `git clean -fd` 精确还原到 HEAD（gitignore 的产物不受影响）。
"""
from __future__ import annotations

import os
import re
import subprocess
from dataclasses import dataclass

import dataclasses

from ..audit import report_text
from .runner import AIProfile, run_ai

_FENCE = re.compile(r"```(?:diff|patch)?[ \t]*\n(.*?)```", re.S)
_DEFAULT_TEST_CMD = ["uv", "run", "python", "-m", "unittest", "discover", "-s", "tests"]


@dataclass
class AutoResult:
    ok: bool
    stage: str          # no-diff/dirty/apply-failed/tests-failed/commit-failed/committed/committed-no-push
    message: str
    diff: str = ""
    test_tail: str = ""


def extract_diff(text: str) -> str:
    """从 AI 输出里取统一 diff：优先 ```diff 围栏，否则从 'diff --git' 起到末尾。"""
    if not text:
        return ""
    for m in _FENCE.finditer(text):
        blk = m.group(1)
        if "diff --git" in blk or blk.lstrip().startswith("--- "):
            return blk.strip("\n") + "\n"
    i = text.find("diff --git ")
    if i >= 0:
        return text[i:].rstrip() + "\n"
    return ""


def _run(args, cwd, stdin=None):
    return subprocess.run(args, cwd=cwd, input=stdin, capture_output=True,
                          text=True, encoding="utf-8", errors="replace")


def _is_clean(repo: str) -> bool:
    r = _run(["git", "status", "--porcelain"], repo)
    return r.returncode == 0 and not r.stdout.strip()


def _rollback(repo: str):
    _run(["git", "reset", "--hard", "HEAD"], repo)
    _run(["git", "clean", "-fd"], repo)      # 清掉 diff 新增的未跟踪文件（gitignore 的不动）


def find_repo() -> str | None:
    """从本包向上找含 .git 的项目根（仅源码 checkout 下有；打包 exe 返回 None）。"""
    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    d = here
    for _ in range(6):
        if os.path.isdir(os.path.join(d, ".git")):
            return d
        parent = os.path.dirname(d)
        if parent == d:
            break
        d = parent
    return None


def apply_test_and_commit(repo: str, diff: str, test_cmd, commit_msg: str,
                          push: bool = False) -> AutoResult:
    """应用 diff → 跑 test_cmd → 全过提交(可选推送)，否则回滚。绝不让坏改动留存。"""
    if not diff.strip():
        return AutoResult(False, "no-diff", "AI 未产出可应用的 diff")
    if not _is_clean(repo):
        return AutoResult(False, "dirty", "工作区有未提交改动，请先提交或暂存后再自动优化")

    ap = _run(["git", "apply", "--whitespace=nowarn"], repo, stdin=diff)
    if ap.returncode != 0:
        ap = _run(["git", "apply", "--3way", "--whitespace=nowarn"], repo, stdin=diff)
    if ap.returncode != 0:
        _rollback(repo)
        return AutoResult(False, "apply-failed", "diff 无法应用，已回滚：" + ap.stderr[:300], diff=diff)

    t = subprocess.run(test_cmd, cwd=repo, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    tail = ((t.stdout or "") + "\n" + (t.stderr or "")).strip()[-2000:]
    if t.returncode != 0:
        _rollback(repo)
        return AutoResult(False, "tests-failed", "测试未通过，已回滚到改前", diff=diff, test_tail=tail)

    _run(["git", "add", "-A"], repo)
    c = _run(["git", "commit", "-m", commit_msg], repo)
    if c.returncode != 0:
        return AutoResult(False, "commit-failed", "提交失败：" + c.stderr[:200], diff=diff, test_tail=tail)
    if push:
        p = _run(["git", "push"], repo)
        if p.returncode != 0:
            return AutoResult(True, "committed-no-push", "已提交，但推送失败：" + p.stderr[:200],
                              diff=diff, test_tail=tail)
    return AutoResult(True, "committed",
                      "已应用、测试通过、提交" + ("并推送" if push else ""), diff=diff, test_tail=tail)


def run_auto_optimize(diag, profile: AIProfile, repo: str | None = None,
                      test_cmd=None, push: bool = True,
                      prompts_dir: str | None = None) -> AutoResult:
    """全自动：让 AI 读仓库源码 + 诊断，直接产出修复 diff，应用并测试，绿了提交推送。"""
    repo = repo or find_repo()
    if not repo:
        return AutoResult(False, "no-repo", "未找到源码仓库（仅开发环境/源码运行可用）")
    test_cmd = test_cmd or _DEFAULT_TEST_CMD

    from .improve import load_prompt, build_prompt
    template = load_prompt("autopt", prompts_dir)
    prompt = build_prompt(template, diag)
    # 让 AI 在仓库目录里跑，可自行读 w3xtool/ 源码
    prof = dataclasses.replace(profile, cwd=repo)
    res = run_ai(prof, prompt)
    if not res.ok:
        return AutoResult(False, "ai-failed", "AI 调用失败：" + res.error)
    diff = extract_diff(res.stdout)
    return apply_test_and_commit(repo, diff, test_cmd,
                                 "AI 自动优化解析逻辑（基于 %s 诊断）" % diag.name, push=push)
