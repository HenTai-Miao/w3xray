"""save_codes 提取逻辑测试 (正则/载体/转义/假阳性)。"""

from w3xtool.save_codes import extract_save_codes, extract_script_save_codes


def test_preload_literal_extraction():
    text = 'call Preload( "-load QWER-ASDF-ZXCV" )\n'
    hits = extract_save_codes(text)
    assert len(hits) == 1
    assert hits[0].command == "-load"
    assert hits[0].code.startswith("-load")
    assert hits[0].source == "plain"
    assert hits[0].line == 1


def test_tooltip_call_extraction():
    text = "call BlzSetAbilityTooltip('A000', \"-load MYCODE12345\", 0)\n"
    hits = extract_script_save_codes(text)
    assert len(hits) == 1
    assert hits[0].code == "-load MYCODE12345"
    assert hits[0].source == "script"


def test_short_prefix_ignored():
    text = 'call Preload( "-load ab" )\n'
    assert extract_save_codes(text) == []


def test_plain_line_without_call_ignored():
    text = 'let s = "-load SHOULDNOTMATCH123"\n'
    assert extract_save_codes(text) == []


def test_line_numbers_reported():
    text = 'a\nb\nc\ncall Preload( "-load LINE3CODE99" )\n'
    hits = extract_save_codes(text)
    assert hits and hits[0].line == 4


class TestScanBudget:
    def test_timeout_flag(self):
        import time

        from w3xtool.live_handle_chain import ScanBudget

        b = ScanBudget(deadline_s=0.01)
        assert b.check()
        time.sleep(0.03)
        assert not b.check()
        assert b.timed_out

    def test_cancelled(self):
        from w3xtool.live_handle_chain import ScanBudget

        b = ScanBudget(cancelled=True)
        assert not b.check()
        assert not b.timed_out

    def test_no_deadline_never_times_out(self):
        from w3xtool.live_handle_chain import ScanBudget

        b = ScanBudget()
        assert b.check()
        assert not b.timed_out

    def test_unit_field_layout_complete(self):
        from w3xtool.live_handle_chain import UNIT_FIELD_LAYOUT

        assert UNIT_FIELD_LAYOUT["inventory"][0] == 0x1F8
        assert UNIT_FIELD_LAYOUT["owner_slot"][0] == 0x58
        assert all(isinstance(v[0], int) and v[1] for v in UNIT_FIELD_LAYOUT.values())
