"""知识包导出脚本触发注册索引。"""

import os
import tempfile
import unittest

from w3xtool.api import MapData
from w3xtool.knowledge_pack import write_knowledge_pack


class KnowledgePackScriptTriggerRegistrationIndexTest(unittest.TestCase):
    def test_pack_exports_script_trigger_registration_index(self):
        # Given: a parsed map with trigger event and action wiring in script code.
        md = MapData(path="x.w3x", name="触发注册索引图")
        md.scripts = {
            "war3map.j": "\n".join((
                "function InitTrig_Save takes nothing returns nothing",
                "    call TriggerRegisterPlayerEvent(gg_trg_Save, Player(0), EVENT_PLAYER_LEAVE)",
                "    call TriggerAddAction(gg_trg_Save, function Trig_Save_Actions)",
                "endfunction",
            )),
        }

        # When: the user exports the knowledge pack.
        with tempfile.TemporaryDirectory() as out:
            write_knowledge_pack(md, out)

            # Then: the pack contains trigger registration control-flow rows.
            with open(os.path.join(out, "脚本触发注册索引.tsv"), encoding="utf-8") as f:
                index = f.read()
            self.assertIn("来源\t行号\t函数\t注册类型\t句柄\tAPI\t目标\t字符串参数\t摘要", index)
            self.assertIn(
                "war3map.j\t2\tInitTrig_Save\t事件\tgg_trg_Save\tTriggerRegisterPlayerEvent\tEVENT_PLAYER_LEAVE",
                index,
            )
            self.assertIn(
                "war3map.j\t3\tInitTrig_Save\t动作\tgg_trg_Save\tTriggerAddAction\tTrig_Save_Actions",
                index,
            )

            with open(os.path.join(out, "资料包目录.tsv"), encoding="utf-8") as f:
                manifest = f.read()
            self.assertIn("脚本\t脚本触发注册索引.tsv\t脚本事件、动作、条件和计时器入口", manifest)


if __name__ == "__main__":
    unittest.main()
