"""Release regressions for the lifecycle of read-only live probes."""

import ctypes
from dataclasses import replace
from types import SimpleNamespace
import sys

import pytest


pytestmark = pytest.mark.skipif(sys.platform != "win32", reason="Windows live API")


def test_process_open_requires_read_access_only_and_closes_privilege_token(
    monkeypatch: pytest.MonkeyPatch,
):
    from gametool import live_inventory as live

    closed = []

    def open_token(_process, _access, output):
        output._obj.value = 0x123
        return True

    def open_read_process(access, inherit, pid):
        assert not inherit and pid == 42
        return 100 if access == 0x0410 else None

    api = SimpleNamespace(
        GetCurrentProcess=lambda: -1,
        OpenProcessToken=open_token,
        OpenProcess=open_read_process,
        CloseHandle=lambda handle: closed.append(handle.value),
    )
    token_api = SimpleNamespace(
        OpenProcessToken=open_token,
        LookupPrivilegeValueW=lambda *_args: True,
        AdjustTokenPrivileges=lambda *_args: True,
    )
    monkeypatch.setattr(live, "k32", api)
    monkeypatch.setattr(live, "adv", token_api)

    assert live.open_process(42) == 100
    assert closed == [0x123]


def test_integrity_size_query_continues_and_closes_token(
    monkeypatch: pytest.MonkeyPatch,
):
    from gametool import live_inventory as live

    closed = []

    def open_token(_process, _access, output):
        output._obj.value = 0x123
        return True

    def token_information(_token, _kind, buffer, length, required):
        required._obj.value = ctypes.sizeof(ctypes.c_void_p)
        if length == 0:
            return False  # ERROR_INSUFFICIENT_BUFFER is the normal size-query result.
        ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0] = 0x1234
        return True

    subauthority_count = ctypes.c_ubyte(1)
    subauthority = ctypes.c_ulong(0x3000)
    api = SimpleNamespace(
        OpenProcessToken=open_token,
        GetTokenInformation=token_information,
        GetSidSubAuthorityCount=lambda _sid: ctypes.pointer(subauthority_count),
        GetSidSubAuthority=lambda _sid, _index: ctypes.pointer(subauthority),
    )
    monkeypatch.setattr(ctypes, "WinDLL", lambda *_args, **_kwargs: api)
    monkeypatch.setattr(
        live, "k32", SimpleNamespace(CloseHandle=lambda h: closed.append(h.value))
    )

    assert live._integrity_rid(42) == 0x3000
    assert closed == [0x123]


def test_live_probe_closes_process_even_if_version_detection_raises(
    monkeypatch: pytest.MonkeyPatch,
):
    from gametool import live_inventory as live

    closed = []
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(live, "_process_identity", lambda _h: "game.exe")
    monkeypatch.setattr(live, "_integrity_rid", lambda _h: None)
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=closed.append))

    def failed_version(_h):
        raise OSError("fixture module failure")

    monkeypatch.setattr(live, "detect_version", failed_version)
    with pytest.raises(OSError, match="fixture module failure"):
        live.read_live(None, verbose=False)
    assert closed == [123]
    assert live.report_pid() is None


def test_probe_releases_process_after_an_empty_read(monkeypatch: pytest.MonkeyPatch):
    from gametool import live_inventory as live

    closed = []
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(live, "_process_identity", lambda _h: "game.exe")
    monkeypatch.setattr(live, "_integrity_rid", lambda _h: None)
    monkeypatch.setattr(live, "snapshot", lambda *_args: ([], 0))
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=closed.append))
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _h: {
            "arch": "x86",
            "engine": "unknown",
            "version": None,
            "game_dll": None,
        },
    )

    result = live.read_live(None, strategy="handle", verbose=False)

    assert result["pid"] == 42
    assert result["slots"] == []
    assert closed == [123]
    assert live.report_pid() is None


@pytest.mark.parametrize("unit_query", (None, "H004"))
def test_confirmed_empty_inventory_never_uses_another_units_fallback(
    tmp_path, monkeypatch: pytest.MonkeyPatch, capsys, unit_query
):
    from gametool import hero_chain, live_handle_chain as hc, live_inventory as live
    from tests.test_live_handle_chain import DLL_BASE, _build_memory
    from tests.test_live_process_images import snapshot_image

    regions, _hero, _other, _offsets = _build_memory()
    image, image_binding = snapshot_image(DLL_BASE)
    regions.append((DLL_BASE, image))
    # Empty the selected unit's slots while the other unit keeps three items.
    regions = [
        (base, bytes(len(payload)) if base == 0x10010000 else payload)
        for base, payload in regions
    ]
    profile = replace(
        hc.resolve_profile("1.27.0.52240", "classic", "x86"),
        checks=(),
        fingerprint=None,
    )
    monkeypatch.setattr(hc, "resolve_profile", lambda *_args: profile)
    monkeypatch.setattr(live, "mem_setup", lambda: None)
    monkeypatch.setattr(live, "find_war3_pids", lambda: [42])
    monkeypatch.setattr(live, "open_process", lambda _pid: 123)
    monkeypatch.setattr(live, "_process_identity", lambda _h: "game.exe")
    monkeypatch.setattr(live, "_integrity_rid", lambda _h: None)
    monkeypatch.setattr(live, "snapshot", lambda *_args: (regions, 0))
    monkeypatch.setattr(live, "k32", SimpleNamespace(CloseHandle=lambda _h: None))
    monkeypatch.setattr(
        live,
        "detect_version",
        lambda _h: {
            "arch": "x86",
            "engine": "classic",
            "version": "1.27.0.52240",
            **image_binding,
        },
    )
    monkeypatch.setattr(
        hero_chain,
        "read_inventory",
        lambda *_args, **_kwargs: [{"slot": 0, "code": "I07F", "name": "decoy item"}],
    )

    result = live.read_live(str(tmp_path), unit_query=unit_query, verbose=False)

    assert result["strategy_used"] == "handle"
    assert result["selected_unit"]["code"] == "H004"
    assert result["slots"] == []
    assert result["selected_unit"]["items"] == []
    monkeypatch.setattr(live, "read_live", lambda *_args, **_kwargs: result)
    assert live.main(["--pack", str(tmp_path)]) == 0
    assert "H004" in capsys.readouterr().out
