"""脚本扫描覆盖面：聊天指令 BJ 封装 + Lua FourCC 码写法。"""
import unittest

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


class TestCodesIn(unittest.TestCase):
    def test_single_quoted(self):
        self.assertIn("hfoo", _codes_in("call CreateUnit(p, 'hfoo', 0,0,0)"))

    def test_lua_fourcc_double_quoted(self):
        self.assertIn("hpea", _codes_in('local id = FourCC("hpea")'))

    def test_lua_fourcc_single_quoted(self):
        self.assertIn("ewsp", _codes_in("FourCC('ewsp')"))


if __name__ == "__main__":
    unittest.main()
