"""解析诊断：把一张图的'缺斤少两'信号结构化，供 AI 归因或人工审阅。

把现有 tools_audit.py 的临时逻辑升格为正式模块：
- name_quality / diagnose 是纯函数，吃已解析的数据，可独立单测；
- audit_map / batch_audit 是 IO 包装，负责打开地图、捕获解析告警。
"""
from __future__ import annotations

import contextlib
import glob
import io
import os
from dataclasses import dataclass, field

from .w3obj import EXT_CATEGORY

# 标准对象数据文件 → 类别（用于"文件存在但 0 对象"检测）
_OBJ_FILES = {"war3map." + ext: cat for ext, cat in EXT_CATEGORY.items()}


@dataclass
class MapDiagnostic:
    path: str
    name: str
    ok: bool = True
    error: str = ""
    total_objects: int = 0
    category_counts: dict = field(default_factory=dict)
    named: int = 0
    bare_id: int = 0
    mojibake: int = 0
    scripts: list = field(default_factory=list)
    commands: int = 0
    recipes: int = 0
    empty_object_files: list = field(default_factory=list)  # 文件在档但 0 对象
    warnings: list = field(default_factory=list)            # 解析期 stderr 告警
    flags: list = field(default_factory=list)               # 人类可读的疑似缺口


def name_quality(objects):
    """统计 (有真名, 无名/裸ID, 乱码) 三类数量。"""
    good = bad = mojibake = 0
    for o in objects:
        nm = o.name or ""
        if "�" in nm:
            mojibake += 1
        if (not nm) or nm.startswith("ID:") or nm == o.obj_id or nm == o.base_id:
            bad += 1
        else:
            good += 1
    return good, bad, mojibake


def diagnose(md, archive_files) -> MapDiagnostic:
    """从已解析的 MapData + 档内文件名列表，算出结构化诊断（纯函数）。"""
    allobj = [o for v in md.objects.values() for o in v]
    good, bad, moji = name_quality(allobj)
    counts = {k: len(v) for k, v in md.objects.items() if v}

    # 文件存在但对应类别 0 对象 → 疑似漏解析
    present = {f.lower() for f in (archive_files or [])}
    empty = []
    for fn, cat in _OBJ_FILES.items():
        if fn in present and not md.objects.get(cat):
            empty.append(fn)

    diag = MapDiagnostic(
        path=md.path, name=md.name, total_objects=len(allobj),
        category_counts=counts, named=good, bare_id=bad, mojibake=moji,
        scripts=list(md.scripts.keys()), empty_object_files=empty,
    )

    flags = []
    for fn in empty:
        flags.append("%s 存在但提取到 0 个 %s" % (fn, _OBJ_FILES[fn]))
    if not any(s in md.scripts for s in ("war3map.j", "war3map.lua")):
        flags.append("没有提取到脚本(war3map.j/lua)")
    if allobj and good / len(allobj) < 0.8:
        flags.append("名字解析率偏低(%.0f%%)" % (good / len(allobj) * 100))
    if moji:
        flags.append("%d 个对象名疑似乱码(含替换符)" % moji)
    diag.flags = flags
    return diag


def report_text(diag: MapDiagnostic) -> str:
    """把诊断渲染成给 AI / 人看的纯文本报告（嵌进提示词）。"""
    lines = []
    lines.append("# 地图解析诊断：%s" % diag.name)
    lines.append("路径：%s" % diag.path)
    if not diag.ok:
        lines.append("解析失败：%s" % diag.error)
        return "\n".join(lines)
    lines.append("对象总数：%d（有名 %d / 无名 %d / 乱码 %d）"
                 % (diag.total_objects, diag.named, diag.bare_id, diag.mojibake))
    lines.append("各类别：" + ("、".join("%s=%d" % (k, v)
                 for k, v in diag.category_counts.items()) or "无"))
    lines.append("脚本文件：" + ("、".join(diag.scripts) or "无"))
    lines.append("隐藏指令：%d　合成配方：%d" % (diag.commands, diag.recipes))
    if diag.empty_object_files:
        lines.append("文件在档但 0 对象：" + "、".join(diag.empty_object_files))
    if diag.warnings:
        lines.append("解析告警（%d 条）：" % len(diag.warnings))
        lines.extend("  - " + w for w in diag.warnings[:20])
    if diag.flags:
        lines.append("疑似缺口：")
        lines.extend("  - " + f for f in diag.flags)
    return "\n".join(lines)


def audit_map(path: str) -> MapDiagnostic:
    """打开并解析一张图，返回诊断（捕获解析告警，绝不抛异常）。"""
    from .api import load_map, commands_from_map, recipes_from_map
    from .mpq import MPQArchive
    warn = io.StringIO()
    try:
        with contextlib.redirect_stderr(warn):
            md = load_map(path)
    except Exception as e:
        return MapDiagnostic(path=path, name=os.path.basename(path),
                             ok=False, error=repr(e)[:200])
    try:
        files = MPQArchive(path).list_files()
    except Exception:
        files = list(getattr(md, "all_files", []) or [])
    diag = diagnose(md, files)
    diag.warnings = [l for l in warn.getvalue().splitlines() if l.strip()]
    try:
        diag.commands = len(commands_from_map(md))
        diag.recipes = len(recipes_from_map(md))
    except Exception:
        pass
    if diag.warnings:
        diag.flags.append("解析期有 %d 条告警" % len(diag.warnings))
    return diag


def batch_audit(directory: str) -> list:
    """审计一个目录下所有 .w3x/.w3m/.w3n。"""
    maps = sorted(glob.glob(os.path.join(directory, "*.w3x"))
                  + glob.glob(os.path.join(directory, "*.w3m"))
                  + glob.glob(os.path.join(directory, "*.w3n")))
    return [audit_map(m) for m in maps]
