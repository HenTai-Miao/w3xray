"""指令/配方扫描复用已解析的 MapData，避免重复打开同一个 MPQ。

commands_from_map / recipes_from_map 直接吃 md.scripts，
结果应与把同一段脚本喂给底层扫描器一致；无脚本时返回空。
"""
import unittest

from w3xtool.api import MapData, commands_from_map, recipes_from_map
from w3xtool.script_scan import scan_chat_commands
from w3xtool.script_scan import scan_recipes as _scan_recipes_text


# 一段含聊天指令的 JASS 片段（足够触发 scan_chat_commands）
SAMPLE_JASS = '''
function Trig_cmd takes nothing returns boolean
    if SubStringBJ(GetEventPlayerChatString(), 1, 4) == "-kill" then
        call BJDebugMsg("killed")
    endif
    return false
endfunction
'''


class TestMapReuse(unittest.TestCase):
    def test_commands_from_map_matches_direct_scan(self):
        md = MapData(path="x", name="x", scripts={"war3map.j": SAMPLE_JASS})
        self.assertEqual(commands_from_map(md), scan_chat_commands(SAMPLE_JASS))

    def test_recipes_from_map_matches_direct_scan(self):
        md = MapData(path="x", name="x", scripts={"war3map.j": SAMPLE_JASS})
        self.assertEqual(recipes_from_map(md), _scan_recipes_text(SAMPLE_JASS))

    def test_no_script_returns_empty(self):
        md = MapData(path="x", name="x", scripts={})
        self.assertEqual(commands_from_map(md), [])
        self.assertEqual(recipes_from_map(md), [])


if __name__ == "__main__":
    unittest.main()
