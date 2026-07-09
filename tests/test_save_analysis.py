"""脚本存档/同步线索扫描。"""

import unittest

from w3xtool.api import MapData
from w3xtool.save_analysis import build_save_report, format_save_report_tsv


class SaveAnalysisTest(unittest.TestCase):
    def test_detects_gamecache_hashtable_preload_sync_and_object_codes(self):
        # Given: a map script that reads/writes local persistence-like data.
        md = MapData(path="x.w3x", name="存档图")
        md.scripts = {
            "war3map.j": "\n".join((
                'set udg_cache = InitGameCache("AnimeSave.w3v")',
                'call StoreInteger(udg_cache, "hero", "level", GetHeroLevel(u))',
                "set udg_hash = InitHashtable()",
                "call SaveInteger(udg_hash, GetHandleId(p), StringHash(\"gold\"), 99)",
                'call PreloadGenEnd("save\\hero.txt")',
                'call BlzSendSyncData("SAVE", code)',
                "call UnitAddAbility(u, 'A001')",
                "call CreateUnit(Player(0), 'H001', 0, 0, 0)",
            )),
        }

        # When: the report is built.
        report = build_save_report(md)
        text = "\n".join(row.summary for row in report.rows)

        # Then: persistence mechanisms and object IDs are grouped for investigation.
        self.assertEqual(report.total, 9)
        self.assertIn("GameCache", report.mechanism_counts)
        self.assertIn("Hashtable", report.mechanism_counts)
        self.assertIn("Preload", report.mechanism_counts)
        self.assertIn("Sync", report.mechanism_counts)
        self.assertIn("HandleKey", report.mechanism_counts)
        self.assertIn("HashKey", report.mechanism_counts)
        self.assertIn("AnimeSave.w3v", text)
        self.assertIn("save\\hero.txt", text)
        self.assertIn("AnimeSave.w3v", report.local_files)
        self.assertIn("save\\hero.txt", report.local_files)
        self.assertIn("hero", report.sections)
        self.assertIn("level", report.keys)
        self.assertIn("gold", report.keys)
        self.assertIn("SAVE", report.sync_prefixes)
        self.assertIn("A001", report.object_codes)
        self.assertIn("H001", report.object_codes)

        tsv = format_save_report_tsv(report)
        self.assertIn("存档文件\t区段/父键\t键/子键\t同步前缀", tsv)
        self.assertIn("AnimeSave.w3v", tsv)
        self.assertIn("hero\tlevel", tsv)
        self.assertIn("GetHandleId(p)\tgold", tsv)

    def test_detects_multiline_save_and_object_calls(self):
        # Given: map authors often wrap long save and object calls across lines.
        md = MapData(path="x.w3x", name="跨行存档图")
        md.scripts = {
            "war3map.j": "\n".join((
                "call StoreInteger(",
                "    udg_cache,",
                '    "hero",',
                '    "level",',
                "    10",
                ")",
                "call UnitAddAbility(",
                "    u,",
                "    'A001'",
                ")",
            )),
        }

        # When: the save report is built.
        report = build_save_report(md)

        # Then: cross-line context is still captured for investigation exports.
        self.assertIn("hero", report.sections)
        self.assertIn("level", report.keys)
        self.assertIn("A001", report.object_codes)
        tsv = format_save_report_tsv(report)
        self.assertIn("war3map.j\t1\tGameCache\t写整数", tsv)
        self.assertIn("war3map.j\t7\tObjectID\t技能", tsv)

    def test_ignores_save_and_object_calls_inside_comments_and_strings(self):
        # Given: comments and player-facing strings mention code-like snippets.
        md = MapData(path="x.w3x", name="误报存档图")
        md.scripts = {
            "war3map.j": "\n".join((
                '// call StoreInteger(udg_cache, "fake", "key", 1)',
                '-- call SaveInteger(udg_hash, 1, StringHash("lua_fake"), 2)',
                'call BJDebugMsg("call SaveInteger(udg_hash, 1, StringHash(\\"fake\\"), 2)")',
                "call BJDebugMsg(\"call UnitAddAbility(u, 'A999')\")",
                'call StoreInteger(udg_cache, "real", "level", 1)',
                "call UnitAddAbility(u, 'A001')",
            )),
        }

        # When: the save report is built.
        report = build_save_report(md)

        # Then: only real code calls are treated as save/ID clues.
        self.assertEqual(report.total, 2)
        self.assertIn("real", report.sections)
        self.assertIn("level", report.keys)
        self.assertIn("A001", report.object_codes)
        self.assertNotIn("fake", report.sections)
        self.assertNotIn("fake", report.keys)
        self.assertNotIn("lua_fake", report.keys)
        self.assertNotIn("A999", report.object_codes)

    def test_detects_platform_save_api_keys_without_executing_them(self):
        # Given: RPG maps often use platform save APIs for cloud/server persistence.
        md = MapData(path="x.w3x", name="平台存档图")
        md.scripts = {
            "war3map.lua": "\n".join((
                'DzAPI_Map_SaveServerValue(Player(0), "hero.level", "25")',
                'DzAPI_Map_GetServerValue(Player(0), "hero.level")',
                'DzAPI_Map_StoreInteger(Player(0), "bag", "slot1", 1001)',
                'DzAPI_Map_GetStoredInteger(Player(0), "bag", "slot1")',
                'DzAPI_Map_SavePublicArchive(Player(0), "season.rank", "A")',
                'KKAPI_SaveServerValue(Player(0), "kk.hero", "ok")',
            )),
        }

        # When: the report is built.
        report = build_save_report(md)
        tsv = format_save_report_tsv(report)

        # Then: platform save keys are visible as static clues only.
        self.assertEqual(report.mechanism_counts.get("PlatformSave"), 6)
        self.assertIn("hero.level", report.keys)
        self.assertIn("bag", report.sections)
        self.assertIn("slot1", report.keys)
        self.assertIn("season.rank", report.keys)
        self.assertIn("kk.hero", report.keys)
        self.assertIn("DzAPI_Map_SaveServerValue", tsv)
        self.assertIn("KKAPI_SaveServerValue", tsv)

    def test_detects_wide_hashtable_handle_native_family(self):
        # Given: Warcraft hashtable natives include many handle-specific save/load calls.
        md = MapData(path="x.w3x", name="句柄存档图")
        md.scripts = {
            "war3map.j": "\n".join((
                'call SavePlayerHandle(udg_hash, StringHash("player"), StringHash("owner"), p)',
                'call SaveTimerHandle(udg_hash, StringHash("timer"), StringHash("respawn"), t)',
                'set trg = LoadTriggerHandle(udg_hash, StringHash("system"), StringHash("spawn"))',
                'if HaveSavedHandle(udg_hash, StringHash("system"), StringHash("spawn")) then',
                'call RemoveSavedHandle(udg_hash, StringHash("system"), StringHash("spawn"))',
            )),
        }

        # When: the save report is built.
        report = build_save_report(md)
        tsv = format_save_report_tsv(report)

        # Then: the broader native family is reported with parent/key context.
        self.assertEqual(report.mechanism_counts.get("Hashtable"), 5)
        self.assertIn("player", report.sections)
        self.assertIn("owner", report.keys)
        self.assertIn("system", report.sections)
        self.assertIn("spawn", report.keys)
        self.assertIn("SavePlayerHandle", tsv)
        self.assertIn("SaveTimerHandle", tsv)
        self.assertIn("LoadTriggerHandle", tsv)
        self.assertIn("HaveSavedHandle", tsv)
        self.assertIn("RemoveSavedHandle", tsv)


if __name__ == "__main__":
    unittest.main()
