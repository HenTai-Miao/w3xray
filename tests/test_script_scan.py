"""脚本扫描覆盖面：聊天指令 BJ 封装 + Lua FourCC 码写法。"""
import unittest

from w3xtool.api import MapData, commands_from_map
from w3xtool.script_scan import scan_chat_commands, _codes_in


class TestChatCommands(unittest.TestCase):
    def test_native_form(self):
        js = 'call TriggerRegisterPlayerChatEvent(gg_trg_a, Player(0), "-kill", true)'
        self.assertIn("-kill", [c.command for c in scan_chat_commands(js)])

    def test_bj_wrapper_form(self):
        # GUI 触发器常用 ...BJ，参数顺序不同：trigger, 字符串, exactMatch, player
        js = 'call TriggerRegisterPlayerChatEventBJ(gg_trg_b, "-hp", true, Player(0))'
        cmds = {c.command: c for c in scan_chat_commands(js)}
        self.assertIn("-hp", cmds)
        self.assertTrue(cmds["-hp"].exact)

    def test_bj_prefix_form_not_exact(self):
        js = 'call TriggerRegisterPlayerChatEventBJ(t, "-gold ", false, p)'
        cmds = {c.command: c for c in scan_chat_commands(js)}
        self.assertIn("-gold ", cmds)
        self.assertFalse(cmds["-gold "].exact)


class TestCommandHintTrigstr(unittest.TestCase):
    def test_hint_trigstr_resolved_from_wts(self):
        # 指令提示文本是 TRIGSTR_ 引用时，应查 war3map.wts 还原成真文本
        js = ('function Trig_Brew_Actions takes nothing returns nothing\n'
              'call DisplayTextToPlayer(Player(0), 0, 0, "TRIGSTR_3482")\n'
              'endfunction\n'
              'call TriggerRegisterPlayerChatEvent(gg_trg_Brew, Player(0), "-brewing", true)')
        wts = "STRING 3482\n{\n酿造：输入 -brewing 开始\n}\n"
        md = MapData(path="x", name="x", scripts={"war3map.j": js, "war3map.wts": wts})
        cmds = {c.command: c for c in commands_from_map(md)}
        self.assertIn("-brewing", cmds)
        self.assertEqual(cmds["-brewing"].hint, "酿造：输入 -brewing 开始")

    def test_hint_without_wts_left_asis(self):
        js = ('function Trig_X_Actions takes nothing returns nothing\n'
              'call DisplayTextToPlayer(Player(0), 0, 0, "直接文本")\n'
              'endfunction\n'
              'call TriggerRegisterPlayerChatEvent(gg_trg_X, Player(0), "-x", true)')
        md = MapData(path="x", name="x", scripts={"war3map.j": js})
        cmds = {c.command: c for c in commands_from_map(md)}
        self.assertEqual(cmds["-x"].hint, "直接文本")


class TestCodesIn(unittest.TestCase):
    def test_single_quoted(self):
        self.assertIn("hfoo", _codes_in("call CreateUnit(p, 'hfoo', 0,0,0)"))

    def test_lua_fourcc_double_quoted(self):
        self.assertIn("hpea", _codes_in('local id = FourCC("hpea")'))

    def test_lua_fourcc_single_quoted(self):
        self.assertIn("ewsp", _codes_in("FourCC('ewsp')"))


if __name__ == "__main__":
    unittest.main()
