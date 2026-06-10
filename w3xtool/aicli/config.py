"""AI CLI 配置：内置 claude/codex/opencode 预设，存取到用户目录。

只存命令模板与选择，绝不存密钥/登录态（登录交给各 CLI 自己）。
配置默认放 ~/.w3xray/ai_config.json。
"""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field

from .runner import AIProfile

# 内置预设：命令为最佳猜测，用户可在设置里改成自己环境里的实际用法。
PRESETS = {
    "claude": AIProfile(name="claude", command=["claude", "-p", "{prompt}"], input_mode="arg"),
    "codex": AIProfile(name="codex", command=["codex", "exec", "{prompt}"], input_mode="arg"),
    "opencode": AIProfile(name="opencode", command=["opencode", "run", "{prompt}"], input_mode="arg"),
}


@dataclass
class AIConfig:
    profiles: list = field(default_factory=list)   # list[AIProfile]
    active: str = ""                               # 当前选中 profile 的 name


def default_config() -> AIConfig:
    profiles = [AIProfile(**vars(p)) for p in PRESETS.values()]
    return AIConfig(profiles=profiles, active="claude")


def config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".w3xray", "ai_config.json")


def get_active(cfg: AIConfig):
    """返回当前选中的 AIProfile；找不到返回 None。"""
    for p in cfg.profiles:
        if p.name == cfg.active:
            return p
    return None


def _profile_to_dict(p: AIProfile) -> dict:
    return {"name": p.name, "command": list(p.command), "cwd": p.cwd,
            "timeout": p.timeout, "input_mode": p.input_mode}


def _profile_from_dict(d: dict) -> AIProfile:
    return AIProfile(
        name=d.get("name", ""),
        command=list(d.get("command", [])),
        cwd=d.get("cwd"),
        timeout=float(d.get("timeout", 300.0)),
        input_mode=d.get("input_mode", "arg"),
    )


def save_config(cfg: AIConfig, path: str | None = None):
    path = path or config_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    data = {"active": cfg.active, "profiles": [_profile_to_dict(p) for p in cfg.profiles]}
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_config(path: str | None = None) -> AIConfig:
    """读配置；文件缺失或损坏都回落到默认配置（含三个预设），绝不抛异常。"""
    path = path or config_path()
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        profiles = [_profile_from_dict(d) for d in data.get("profiles", [])]
        if not profiles:
            return default_config()
        return AIConfig(profiles=profiles, active=data.get("active", ""))
    except (OSError, ValueError, TypeError):
        return default_config()
