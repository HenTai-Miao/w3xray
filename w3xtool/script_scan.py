"""扫描地图脚本(war3map.j / war3map.lua)里的隐藏聊天指令。

抓 TriggerRegisterPlayerChatEvent(trig, player, "指令", 精确?) 的指令字符串，
并尽量在同名触发的动作函数里找一句提示文本作为说明。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

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


def scan_chat_commands(script: str) -> list:
    cmds = []
    seen = set()
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
    ingredients: list      # 材料物品码
    result: str            # 成品物品码
    func: str = ""


_FOURCC = re.compile(r"'([A-Za-z0-9]{4})'")
_HEXCC = re.compile(r"\$([0-9A-Fa-f]{8})")
# Lua 写法：FourCC("xxxx") / FourCC('xxxx')（双引号码不被 _FOURCC 捕获）
_FOURCC_FN = re.compile(r"""FourCC\s*\(\s*["']([A-Za-z0-9]{4})["']\s*\)""")


def _codes_in(s: str):
    """从一段代码里取所有对象码：'xxxx' 文本码 + $XXXXXXXX 十六进制码 + FourCC("xxxx")。"""
    out = list(_FOURCC.findall(s))
    out += _FOURCC_FN.findall(s)
    for h in _HEXCC.findall(s):
        try:
            cc = bytes.fromhex(h).decode("latin-1")
        except Exception:
            continue
        if all(32 <= ord(c) < 127 for c in cc):
            out.append(cc)
    return out
_REMOVE = re.compile(r"RemoveItem|GetItemOfType|UnitRemoveItem|YDWEGetItemOfType")
_ADD = re.compile(r"UnitAddItemById|CreateItemLoc|CreateItem\b|UnitAddItemByIdSwapped")


def scan_recipes(script: str) -> list:
    """识别脚本里的物品合成：函数内被移除的物品=材料，被添加的物品=成品。

    覆盖常见 YDWE/JASS 写法（RemoveItem 材料 + UnitAddItemById 成品）。
    """
    recipes = []
    seen = set()
    # 按函数切分（避免在超大脚本上做灾难性回溯）
    parts = script.split("\nfunction ")
    for part in parts:
        if "AddItemById" not in part and "CreateItem" not in part:
            continue
        name = part[:part.find("\n")].split("(")[0].strip() if "\n" in part else ""
        buffer = []                      # 以"添加成品"为锚点，前面积累的移除物=材料
        for line in part.split("\n"):
            if _REMOVE.search(line):
                buffer.extend(_codes_in(line))
            elif _ADD.search(line):
                for res in _codes_in(line):
                    ing = [i for i in buffer if i != res]
                    if len(ing) < 2:
                        continue
                    key = (tuple(sorted(ing)), res)
                    if key in seen:
                        continue
                    seen.add(key)
                    recipes.append(Recipe(ing, res, name))
                buffer = []              # 结算后清空，下一配方重新积累
    return recipes


_ITEM_NATIVES = re.compile(
    r"UnitAddItemById|UnitAddItemByIdSwapped|CreateItem|CreateItemLoc|"
    r"AddItemToStockBJ|AddItemToAllStock|UnitDropItemPoint|SetItemTypeId")
_UNIT_NATIVES = re.compile(
    r"CreateUnit|CreateNUnitsAtLoc|BlzCreateUnit|CreateUnitAtLoc|GroupEnumUnitsOfType"
    r"|AddUnitToStockBJ|AddUnitToAllStock|ReplaceUnitBJ|SetUnitTypeId")


def scan_object_refs(script: str) -> dict:
    """从脚本按调用类型提取被引用的 物品/单位 代码（用于无 w3t/w3u 的图兜底）。

    返回 {"物品": set(codes), "单位": set(codes)}。
    """
    items, units = set(), set()
    for line in script.split("\n"):
        if _ITEM_NATIVES.search(line):
            for cc in _codes_in(line):
                items.add(cc)
        if _UNIT_NATIVES.search(line):
            for cc in _codes_in(line):
                units.add(cc)
    # 单位码常以小写字母开头或 u/o/h/e/n 起头；物品码多以 I/r/... 起头。
    # 不强行过滤，交给调用上下文；但剔除明显的技能码(以大写A起头且第二位小写?)较难，保持原样。
    return {"物品": items, "单位": units}
