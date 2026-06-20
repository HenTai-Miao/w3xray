"""官方秘籍/调试口令残留检测。"""

from w3xtool.api import MapData
from w3xtool.cheats import build_cheat_report


def test_detects_registered_official_cheat_chat_command():
    # Given: a map registers an official cheat phrase as a chat command.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {
        "war3map.j": (
            'call TriggerRegisterPlayerChatEvent(gg_trg_Debug, Player(0), "whosyourdaddy", true)\n'
        )
    }

    # When: cheat residues are scanned.
    report = build_cheat_report(md)

    # Then: the official cheat phrase is reported as a debug residue.
    item = report.by_phrase["whosyourdaddy"]
    assert item.source == "聊天指令"
    assert item.script == "war3map.j"


def test_detects_official_cheat_string_literal():
    # Given: a script contains an official cheat phrase in a debug string.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {"war3map.j": 'call BJDebugMsg("use greedisgood 999999 for testing")'}

    # When: cheat residues are scanned.
    report = build_cheat_report(md)

    # Then: the suspicious phrase is still surfaced.
    item = report.by_phrase["greedisgood"]
    assert item.source == "脚本文本"


def test_ignores_normal_chat_command():
    # Given: a normal user chat command.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {
        "war3map.j": 'call TriggerRegisterPlayerChatEvent(gg_trg_Help, Player(0), "-help", true)'
    }

    # When: cheat residues are scanned.
    report = build_cheat_report(md)

    # Then: no cheat residue is reported.
    assert report.items == ()
