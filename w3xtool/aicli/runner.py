"""通用 AI CLI 调用：按命令模板渲染并跑子进程，统一捕获结果。

一个 AIProfile 描述「怎么调一个 AI CLI」：命令模板 + 输入方式 + 工作目录 + 超时。
prompt 通过三种方式之一传给 CLI：
- arg ：替换命令里的 {prompt} 占位（适合短提示）
- stdin：管道喂给标准输入（命令里不带占位）
- file ：写临时文件，替换 {prompt_file} 占位（适合超大提示）

设计为容错优先：任何失败（命令不存在/超时/非零退出）都返回 AIResult，不抛异常，
让上层（GUI/脚本）能优雅降级——AI 不可用绝不能影响正常的地图解析。
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import time
from dataclasses import dataclass, field

PROMPT_TOKEN = "{prompt}"
PROMPT_FILE_TOKEN = "{prompt_file}"


@dataclass
class AIProfile:
    name: str
    command: list                 # 参数列表，可含 {prompt} / {prompt_file} 占位
    cwd: str | None = None
    timeout: float = 300.0
    input_mode: str = "arg"       # arg | stdin | file


@dataclass
class AIResult:
    ok: bool
    stdout: str = ""
    stderr: str = ""
    exit_code: int = -1
    duration: float = 0.0
    error: str = ""               # 人类可读的失败原因（成功时空）


def _render(command, prompt, prompt_file):
    out = []
    for arg in command:
        if PROMPT_TOKEN in arg:
            arg = arg.replace(PROMPT_TOKEN, prompt)
        if prompt_file is not None and PROMPT_FILE_TOKEN in arg:
            arg = arg.replace(PROMPT_FILE_TOKEN, prompt_file)
        out.append(arg)
    return out


def run_ai(profile: AIProfile, prompt: str) -> AIResult:
    """按 profile 调一次 AI CLI，把 prompt 传进去，返回统一结果（绝不抛异常）。"""
    tmp_path = None
    stdin_data = None
    mode = (profile.input_mode or "arg").lower()
    try:
        if mode == "file":
            fd, tmp_path = tempfile.mkstemp(suffix=".txt", prefix="w3xray_prompt_")
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(prompt)
            command = _render(profile.command, prompt, tmp_path)
        elif mode == "stdin":
            command = _render(profile.command, prompt, None)
            stdin_data = prompt
        else:  # arg
            command = _render(profile.command, prompt, None)

        start = time.monotonic()
        try:
            proc = subprocess.run(
                command,
                input=stdin_data,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                cwd=profile.cwd or None,
                timeout=profile.timeout,
            )
        except FileNotFoundError:
            return AIResult(ok=False, error="命令未找到：%s" % (command[0] if command else "?"))
        except subprocess.TimeoutExpired:
            return AIResult(ok=False, error="超时（%.0fs）" % profile.timeout,
                            duration=profile.timeout)
        except OSError as e:
            return AIResult(ok=False, error="启动失败：%s" % e)

        duration = time.monotonic() - start
        ok = proc.returncode == 0
        return AIResult(
            ok=ok,
            stdout=proc.stdout or "",
            stderr=proc.stderr or "",
            exit_code=proc.returncode,
            duration=duration,
            error="" if ok else "退出码 %d" % proc.returncode,
        )
    finally:
        if tmp_path:
            try:
                os.remove(tmp_path)
            except OSError:
                pass
