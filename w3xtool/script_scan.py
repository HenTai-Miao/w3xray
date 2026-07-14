"""扫描地图脚本(war3map.j / war3map.lua)里的隐藏聊天指令。

抓 TriggerRegisterPlayerChatEvent(trig, player, "指令", 精确?) 的指令字符串，
并尽量在同名触发的动作函数里找一句提示文本作为说明。
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Final

from .script_mechanics import (
    BJ_CODE_CONSTANTS as BJ_CODE_CONSTANTS,
    BJ_FEATURES as BJ_FEATURES,
    BJ_FUNC_CODES as BJ_FUNC_CODES,
    merge_implicit_object_refs,
    scan_script_features,
)
from .script_tokens import iter_native_call_chunks, script_code_text

_CHAT = re.compile(
    r'TriggerRegisterPlayerChatEvent\s*\(\s*([A-Za-z0-9_]+)\s*,[^,]+,\s*"((?:[^"\\]|\\.)*)"\s*,\s*(true|false)')
# GUI 触发器常用 BJ 封装：TriggerRegisterPlayerChatEventBJ(trig, "cmd", exactMatch, player)
# 注意参数顺序不同：字符串在第 2 位、exactMatch 在第 3 位
_CHAT_BJ = re.compile(
    r'TriggerRegisterPlayerChatEventBJ\s*\(\s*([A-Za-z0-9_]+)\s*,\s*"((?:[^"\\]|\\.)*)"\s*,\s*(true|false)')
# Lua 写法：TriggerRegisterPlayerChatEvent(trig, player, "cmd", true)
_CHAT_LUA = _CHAT

# 提示文本类调用里的字符串
_DISPLAY = re.compile(
    r'(?:DisplayTextToPlayer|DisplayTimedTextToPlayer|DisplayTextToForce|'
    r'BJDebugMsg|DisplayTimedTextToForce)\s*\([^"]*"((?:[^"\\]|\\.)*)"')


@dataclass
class ChatCommand:
    command: str
    exact: bool
    trigger: str
    hint: str = ""


def scan_chat_commands(script: str) -> list[ChatCommand]:
    cmds: list[ChatCommand] = []
    seen: set[tuple[str, bool]] = set()
    for pat in (_CHAT, _CHAT_BJ):
        for m in pat.finditer(script):
            trig, cmd, exact = m.group(1), m.group(2), m.group(3) == "true"
            key = (cmd, exact)
            if key in seen:
                continue
            seen.add(key)
            cmds.append(ChatCommand(cmd, exact, trig, _find_hint(script, trig)))
    # 按指令排序，空串/单字符靠后
    cmds.sort(key=lambda c: (len(c.command) == 0, not c.command.startswith("-"), c.command))
    return cmds


def _find_hint(script: str, trigger: str) -> str:
    """根据触发变量名(gg_trg_Xxx)找对应动作函数里的第一句提示文本。"""
    # gg_trg_Xxx → 函数 Trig_Xxx_Actions
    m = re.search(r'gg_trg_(\w+)', trigger)
    if not m:
        return ""
    base = m.group(1)
    fn = re.search(r'function\s+Trig_' + re.escape(base) + r'_Actions\b(.*?)\nendfunction',
                   script, re.DOTALL)
    if not fn:
        return ""
    body = fn.group(1)
    d = _DISPLAY.search(body)
    if d:
        txt = d.group(1).strip()
        return txt[:60]
    return ""


@dataclass
class Recipe:
    ingredients: list[str]      # 材料物品码
    result: str                  # 成品物品码
    func: str = ""
    source: str = ""
    line: int = 0
    confidence: str = "已确认"
    evidence: str = ""


_FOURCC = re.compile(r"'([A-Za-z0-9]{4})'")
_HEXCC = re.compile(r"\$([0-9A-Fa-f]{8})")
# Lua 写法：FourCC("xxxx") / FourCC('xxxx')（双引号码不被 _FOURCC 捕获）
_FOURCC_FN = re.compile(r"""FourCC\s*\(\s*["']([A-Za-z0-9]{4})["']\s*\)""")
# 整数形式的码：JASS 里 'hpea' 常写成 1752196449 或 0x68706561（借鉴 w3x2lni searchjass）
_HEXINT = re.compile(r"0[xX]([0-9A-Fa-f]{8})\b")
_DECINT = re.compile(r"(?<![\w.])(\d{10})(?![\w.])")
_CODE_MIN = 0x41303030          # 'A000'：阈值以下当普通数字（伤害/金钱），不当码


def _int_to_code(v: int) -> str | None:
    """整数 → 4 字符码：须 ≥'A000' 且 4 字节全可打印 ASCII，否则不是码。"""
    if v < _CODE_MIN or v > 0xFFFFFFFF:
        return None
    b = v.to_bytes(4, "big")
    if all(0x20 <= c < 0x7F for c in b):
        return b.decode("latin-1")
    return None


def _codes_in(s: str) -> list[str]:
    """取所有对象码：'xxxx' 文本码 + $XX/0xXX 十六进制 + FourCC("xxxx") + 十进制整数码。"""
    out = list(_FOURCC.findall(s))
    out += _FOURCC_FN.findall(s)
    for h in _HEXCC.findall(s):
        try:
            cc = bytes.fromhex(h).decode("latin-1")
        except Exception:
            continue
        if all(32 <= ord(c) < 127 for c in cc):
            out.append(cc)
    # 整数字面量形式的码（0x.. 与 10 位十进制），按阈值+可打印过滤普通数字
    for h in _HEXINT.findall(s):
        cc = _int_to_code(int(h, 16))
        if cc:
            out.append(cc)
    for d in _DECINT.findall(s):
        cc = _int_to_code(int(d))
        if cc:
            out.append(cc)
    return out
_REMOVE = re.compile(r"RemoveItem|GetItemOfType|UnitRemoveItem|YDWEGetItemOfType")
_ADD = re.compile(r"UnitAddItemById|CreateItemLoc|CreateItem\b|UnitAddItemByIdSwapped")
_FUNCTION_START = re.compile(r"^\s*(?:local\s+)?function\s+([A-Za-z_][A-Za-z0-9_]*)\b")
_FUNCTION_END = re.compile(r"^\s*endfunction\b")


def scan_recipes(script: str, *, source: str = "") -> list[Recipe]:
    """识别脚本里的物品合成：函数内被移除的物品=材料，被添加的物品=成品。

    覆盖常见 YDWE/JASS 写法（RemoveItem 材料 + UnitAddItemById 成品）。
    """
    recipes: list[Recipe] = []
    seen: set[tuple[str, int, tuple[str, ...], str]] = set()
    current_function = ""
    ingredients: list[str] = []
    code_lines = script_code_text(script).split("\n")
    source_lines = script.split("\n")
    for line_number, (code_line, source_line) in enumerate(
        zip(code_lines, source_lines, strict=True),
        start=1,
    ):
        function = _FUNCTION_START.match(code_line)
        if function is not None:
            current_function = function.group(1)
            ingredients = []
            continue
        if _FUNCTION_END.match(code_line) is not None:
            current_function = ""
            ingredients = []
            continue
        if _REMOVE.search(code_line) is not None:
            ingredients.extend(_codes_in(code_line))
            continue
        if _ADD.search(code_line) is None:
            continue
        for result in _codes_in(code_line):
            materials = [item for item in ingredients if item != result]
            if len(materials) < 2:
                continue
            key = (source, line_number, tuple(sorted(materials)), result)
            if key in seen:
                continue
            seen.add(key)
            recipes.append(
                Recipe(
                    ingredients=materials,
                    result=result,
                    func=current_function,
                    source=source,
                    line=line_number,
                    evidence=source_line,
                ),
            )
        ingredients = []                  # 结算后清空，下一配方重新积累
    return recipes


# native 名 → 对象分类，由 common.j 离线生成（build_jass_natives.py）。
# 知道每个 native 的对象码参数属于哪类，脚本提码就能覆盖全分类(技能/科技/可破坏物…)，
# 而不只是早期手列的 物品/单位 两类。生成数据缺失时退化为空表（scan 退回只认下方少量回退名）。
try:
    from .jass_natives import NATIVE_OBJ_FUNCS as _native_obj_funcs
except ImportError:                     # 生成数据缺失：表置空，scan_* 仍可跑(覆盖变窄)
    _native_obj_funcs = {}
NATIVE_OBJ_FUNCS: Final[Mapping[str, str | None]] = _native_obj_funcs
_CATS = ("单位", "物品", "技能", "科技", "可破坏物", "增益")

# 把所有"带对象码参数"的 native 名编成一个词边界正则，一次扫一行。
_NATIVE_NAMES = sorted(NATIVE_OBJ_FUNCS, key=len, reverse=True)
_NATIVE_RE = re.compile(r"\b(" + "|".join(re.escape(n) for n in _NATIVE_NAMES) + r")\b") \
    if _NATIVE_NAMES else None
# 生成表缺失时的最小回退（保持老行为：物品/单位仍能提到一些）
_FALLBACK_CAT = {
    "CreateUnit": "单位", "CreateUnitAtLoc": "单位", "BlzCreateUnit": "单位",
    "ReplaceUnitBJ": "单位", "SetUnitTypeId": "单位",
    "CreateItem": "物品", "CreateItemLoc": "物品", "UnitAddItemById": "物品",
    "UnitAddAbility": "技能",
}


def _native_cat(name: str) -> str | None:
    return NATIVE_OBJ_FUNCS.get(name, _FALLBACK_CAT.get(name))


def scan_object_refs(script: str) -> dict[str, set[str]]:
    """从脚本按调用的 native 类型提取被引用的对象码，按分类归并。

    返回 {"单位"/"物品"/"技能"/"科技"/"可破坏物"/"增益": set(codes)}。
    依据 common.j 里每个 native 的对象码参数类别（如 UnitAddAbility 的参数是技能码、
    CreateDestructable 是可破坏物码）。一行里若出现多类 native，则该行的码归入各命中类。
    """
    out: dict[str, set[str]] = {category: set() for category in _CATS}
    names_re = _NATIVE_RE
    if names_re is None:                # 无生成表：用最小回退名集
        names_re = re.compile(r"\b(" + "|".join(_FALLBACK_CAT) + r")\b")
    code_script = script_code_text(script)
    for call in iter_native_call_chunks(code_script, names_re):
        hits = names_re.findall(call.text)
        if not hits:
            continue
        cats = {c for c in (_native_cat(n) for n in hits) if c}
        # 仅当该调用块的 native 一致指向单一分类时才归类；多类(嵌套不同类 native)
        # 无法可靠区分哪个码属哪类，不归类——这些码仍会经 scan_all_referenced_codes
        # 的 'xxxx' 字面量并入孤立根集合，只是不在此处错配到某个分类。
        if len(cats) != 1:
            continue
        codes = _codes_in(call.text)
        if not codes:
            continue
        out[next(iter(cats))].update(codes)
    merge_implicit_object_refs(out, script)
    return out


def scan_all_referenced_codes(script: str) -> set[str]:
    """脚本里"可能是对象引用"的全部 4cc 码（用于孤立判定的根集合，宁滥勿缺）。

    = 所有 'xxxx' 文本码 + 各 native 行提到的码 + BJ 隐式码。order/数值已被 _codes_in 之外
    的 'xxxx' 字面量本身天然多为对象码；少量误收(命令串)对"根集合并集"无害(只会少判孤立)。
    """
    # _codes_in 覆盖 'xxxx' + FourCC("xxxx") + $hex + 十进制码（比单认 'xxxx' 更全）
    codes = set(_codes_in(script_code_text(script)))
    for s in scan_object_refs(script).values():
        codes.update(s)
    _feats, implicit = scan_script_features(script)
    codes.update(implicit)
    return codes
