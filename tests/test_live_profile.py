# -*- coding: utf-8 -*-
"""live 版本档案诊断 / 资源锚缓存复验 / journal 落盘 (学自 trainer 架构)。"""

from __future__ import annotations

import json
import struct

import pytest

from w3xtool import live_handle_chain as lh
from w3xtool.live_inventory import append_live_journal

BASE = 0x10000000


def _reader_at(values: dict[int, float]) -> lh.MemoryReader:
    buf = bytearray(0x1000)
    for off, val in values.items():
        struct.pack_into("<f", buf, off, val)
    return lh.MemoryReader([(BASE, bytes(buf))])


@pytest.fixture(autouse=True)
def _reset_anchor_cache():
    lh._resource_anchors = None
    lh._resource_cache_hit = False
    yield
    lh._resource_anchors = None
    lh._resource_cache_hit = False


class TestDescribeLiveProfile:
    def test_verified(self):
        s = lh.describe_live_profile("1.27.0.52240")
        assert "已验证" in s
        assert lh.LIVE_PROFILE_ID in s

    def test_rva_only(self):
        s = lh.describe_live_profile("1.24.4.6387")
        assert "已收录" in s and "公开表" in s

    def test_unknown(self):
        assert "未收录" in lh.describe_live_profile("9.9.9.99999")

    def test_none(self):
        assert "未收录" in lh.describe_live_profile(None)

    def test_reforged_pending(self):
        s = lh.describe_live_profile("2.0.4.24687", "reforged", "x64")
        assert "重制版" in s and "回退" in s


class TestResolveProfile:
    def test_exact_hit(self):
        p = lh.resolve_profile("1.27.0.52240")
        assert p.tier == "exact"
        assert p.handle_chain is not None
        assert p.game_struct_rva == 0xBE40A8
        assert p.unit_list_rva == 0xBE4238

    def test_rva_table_hit(self):
        p = lh.resolve_profile("1.24.4.6387")
        assert p.tier == "rva-table"
        assert p.engine == "classic" and p.arch == "x86"
        assert p.game_struct_rva == 0xACE5E0
        assert p.unit_list_rva == 0xACD44C
        assert p.handle_chain is None

    def test_unknown_classic_falls_to_template(self):
        p = lh.resolve_profile("1.29.0.5971", "classic", "x86")
        assert p.tier == "template"
        assert p.game_struct_rva is None and p.handle_chain is None

    def test_reforged_falls_to_pending(self):
        p = lh.resolve_profile("2.0.4.24687", "reforged", "x64")
        assert p.tier == "reforged-pending"
        assert p.arch == "x64" and p.handle_chain is None

    def test_table_covers_all_rva_versions(self):
        for ver, rva in lh.GAME_STRUCT_RVAS.items():
            p = lh.resolve_profile(ver)
            assert p.game_struct_rva == rva, ver
            assert p.tier in ("exact", "rva-table"), ver


class TestProfileVerification:
    def _reader_at(self, blob, base=BASE):
        return lh.MemoryReader([(base, blob)])

    def test_checks_pass_on_exact_bytes(self):
        import hashlib

        blob = hashlib.sha256(b"seed").digest()
        reader = self._reader_at(blob)
        p = lh.LiveBuildProfile(
            version="t",
            engine="classic",
            arch="x86",
            game_struct_rva=None,
            unit_list_rva=None,
            handle_chain=None,
            tier="rva-table",
            source="t",
            checks=(lh.ProfileCheck(rva=4, expect=blob[4:12], label="w"),),
        )
        ok, fails = lh.verify_profile(reader, BASE, p)
        assert ok and not fails

    def test_checks_fail_reports_diff(self):
        reader = self._reader_at(b"\x90" * 64)
        p = lh.LiveBuildProfile(
            version="t",
            engine="classic",
            arch="x86",
            game_struct_rva=None,
            unit_list_rva=None,
            handle_chain=None,
            tier="rva-table",
            source="t",
            checks=(lh.ProfileCheck(rva=8, expect=b"\x01\x02", label="w"),),
        )
        ok, fails = lh.verify_profile(reader, BASE, p)
        assert not ok and "w@0x8" in fails[0]

    def test_fingerprint_mismatch_fails(self):
        reader = self._reader_at(b"\x00" * 64)
        p = lh.LiveBuildProfile(
            version="t",
            engine="classic",
            arch="x86",
            game_struct_rva=None,
            unit_list_rva=None,
            handle_chain=None,
            tier="exact",
            source="t",
            fingerprint=lh.ProfileFingerprint(machine=0x14C, timestamp=1, image_size=2),
            checks=(lh.ProfileCheck(rva=0, expect=b"\x00" * 4),),
        )
        fp = lh.ProfileFingerprint(machine=0x14C, timestamp=9, image_size=2)
        ok, fails = lh.verify_profile(reader, BASE, p, fp)
        assert not ok and any("PE 指纹不符" in f for f in fails)

    def test_127_profile_carries_real_samples(self):
        p = lh.resolve_profile("1.27.0.52240")
        assert p.fingerprint is not None
        assert p.fingerprint.machine == 0x14C
        assert p.fingerprint.timestamp == 0x56BD0E1C
        assert p.fingerprint.image_size == 0xCD8000
        assert len(p.checks) == 3
        assert all(len(c.expect) == 16 for c in p.checks)

    def test_read_pe_fingerprint_on_real_pe(self):
        import sys

        from w3xtool.live_inventory import read_pe_fingerprint

        fp = read_pe_fingerprint(sys.executable)
        assert fp is not None
        assert fp.machine in (0x14C, 0x8664)
        assert fp.image_size > 0

    def test_read_pe_fingerprint_garbage(self):
        import tempfile

        from w3xtool.live_inventory import read_pe_fingerprint

        with tempfile.NamedTemporaryFile(suffix=".bin", delete=False) as f:
            f.write(b"not a pe" * 32)
            path = f.name
        assert read_pe_fingerprint(path) is None


class TestTokenIntegrity:
    def test_bad_handle_returns_none(self):
        from w3xtool.live_inventory import _token_integrity_level

        assert _token_integrity_level(0) is None

    def test_self_process_returns_name_or_none(self):
        from w3xtool.live_inventory import _token_integrity_level

        lvl = _token_integrity_level(None)
        assert lvl is None or isinstance(lvl, str)

    def test_level_names_complete(self):
        from w3xtool.live_inventory import _INTEGRITY_NAMES

        assert _INTEGRITY_NAMES[0x2000] == "中"
        assert _INTEGRITY_NAMES[0x2100] == "中高"
        assert _INTEGRITY_NAMES[0x3000] == "高"
        assert _INTEGRITY_NAMES[0x4000] == "系统"

    def test_bad_handle_rid_none(self):
        from w3xtool.live_inventory import _integrity_rid

        assert _integrity_rid(0) is None

    def test_directional_preflight_semantics(self):
        from w3xtool.live_inventory import _INTEGRITY_NAMES

        def flag(game, self_):
            return bool(game and self_ and self_ < game)

        assert flag(0x2000, 0x1000)
        assert not flag(0x1000, 0x3000)
        assert not flag(0x2000, 0x2000)
        assert _INTEGRITY_NAMES.get(0x2100) is not None


class TestResourceAnchorCache:
    def test_first_scan_then_cache_hit(self):
        r1 = _reader_at({0x200: 1234.5, 0x240: 567.8})
        rows = lh.find_resource_layout(r1, 1234.5, 567.8)
        assert rows and rows[0].addr == BASE + 0x200
        assert lh.cached_resource_hit() is False
        rows2 = lh.find_resource_layout(r1, 1234.5, 567.8)
        assert lh.cached_resource_hit() is True
        assert rows2[0].addr == BASE + 0x200

    def test_drift_falls_back_to_full_scan(self):
        lh.find_resource_layout(
            _reader_at({0x200: 1234.5, 0x240: 567.8}), 1234.5, 567.8
        )
        r2 = _reader_at({0x200: 9999.0, 0x500: 4321.0, 0x540: 876.0})
        rows = lh.find_resource_layout(r2, 4321.0, 876.0)
        assert lh.cached_resource_hit() is False
        assert rows and rows[0].addr == BASE + 0x500

    def test_no_false_cache_when_no_rows(self):
        rows = lh.find_resource_layout(_reader_at({}), 1234.5, 567.8)
        assert rows == []
        assert lh.cached_resource_hit() is False
        assert lh._resource_anchors is None


class TestAppendLiveJournal:
    def test_writes_jsonl(self, tmp_path, monkeypatch):
        monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path))
        rep = {
            "version": {"version": "1.27.0.52240", "engine": "classic"},
            "strategy_used": "handle",
            "units": [{"addr": 1}],
            "owned_units": None,
            "resources": None,
            "notes": [
                "偏移档案: 1.27.0.52240 已验证 (x; classic-chain-r1-1.27.0.52240)"
            ],
        }
        append_live_journal(rep)
        f = tmp_path / "live" / "journal-v1.jsonl"
        assert f.exists()
        entry = json.loads(f.read_text(encoding="utf-8").splitlines()[-1])
        assert entry["version"] == "1.27.0.52240"
        assert entry["strategy"] == "handle"
        assert entry["units"] == 1
        assert entry["profile_note"] and "已验证" in entry["profile_note"]

    def test_appends_lines(self, tmp_path, monkeypatch):
        monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path))
        append_live_journal({"units": []})
        append_live_journal({"units": []})
        lines = (
            (tmp_path / "live" / "journal-v1.jsonl")
            .read_text(encoding="utf-8")
            .splitlines()
        )
        assert len(lines) == 2

    def test_fail_open(self, tmp_path, monkeypatch):
        blocker = tmp_path / "not-a-dir"
        blocker.write_text("x", encoding="utf-8")
        monkeypatch.setenv("W3XRAY_CACHE_DIR", str(blocker))
        append_live_journal({})  # 目录被文件占位: 静默失败, 不抛出
