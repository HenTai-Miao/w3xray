"""Report and live probe handoffs retain exact supported object identities."""

from __future__ import annotations

from typing import cast

import pytest

from gametool.gui_live_probe import LiveProbeWindow
import gametool.gui_topbar as topbar


class _Selection:
    def __init__(self, text: str) -> None:
        self.text = text

    def get(self, _start, _end) -> str:
        return self.text


class _Hint:
    def configure(self, **_values) -> None:
        pass


class _ProbeHost:
    def __init__(self, text: str) -> None:
        self._output = _Selection(text)
        self._copy_hint = _Hint()


class _QueryHost:
    def __init__(self) -> None:
        self.opened: list[str] = []

    def on_pack_query(self, **kwargs) -> None:
        self.opened.append(kwargs["prefill"])


@pytest.mark.parametrize("code", ["n001", "I!é?", " A0 "])
def test_report_and_live_probe_preserve_full_selected_code(
    code: str,
) -> None:
    host = _QueryHost()

    topbar._code_selected(host, _Selection(code))
    probe = cast(LiveProbeWindow, cast(object, _ProbeHost(code)))
    extracted = LiveProbeWindow._extract_code(probe)

    assert host.opened == [code]
    assert extracted == code


def test_report_handoff_does_not_guess_from_an_unmarked_word() -> None:
    host = _QueryHost()

    topbar._code_selected(host, _Selection("SOMEX"))

    assert host.opened == []
