# -*- coding: utf-8 -*-
"""live 版本档案诊断 / 资源锚缓存复验 / journal 落盘 (学自 trainer 架构)。"""

from __future__ import annotations

import json
import struct

import pytest

from w3xtool import live_handle_chain as lh
from w3xtool import live_inventory as li
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
        assert all(c.domain == "text" for c in p.checks)
        assert p.schema_version == 1

    def test_profile_json_roundtrip(self):
        import json

        p = lh.resolve_profile("1.27.0.52240")
        d = json.loads(json.dumps(lh.profile_to_dict(p)))
        assert d["schema_version"] == 1
        assert d["status"] == "validated"
        assert d["fingerprint"]["machine"] == 0x14C
        assert len(d["checks"]) == 3
        assert d["checks"][0]["domain"] == "text"
        q = lh.profile_from_dict(d)
        assert q.version == p.version
        assert q.fingerprint == p.fingerprint
        assert q.checks == p.checks
        assert q.handle_chain == p.handle_chain
        assert q.schema_version == 1

    def test_profile_from_dict_rejects_unknown_schema(self):
        import pytest

        with pytest.raises(ValueError, match="v2"):
            lh.profile_from_dict(
                {"schema_version": 2, "game_version": "9.9", "id": "x"}
            )

    def test_scan_budget_phases(self):
        """ScanBudget 三相位: 不限时放行 / 超时置位 / 取消不置超时。"""
        import time as _time

        b0 = lh.ScanBudget(deadline_s=0.0)
        assert b0.check() is True and b0.timed_out is False
        b1 = lh.ScanBudget(deadline_s=0.01)
        _time.sleep(0.03)
        assert b1.check() is False and b1.timed_out is True
        b2 = lh.ScanBudget(deadline_s=0.0, cancelled=True)
        assert b2.check() is False and b2.timed_out is False

    def test_log_live_exception_lands_traceback(self, tmp_path, monkeypatch):
        """诊断日志三件套: 栈+阶段+pid 落盘, notes 拿到路径, fail-open。"""
        monkeypatch.setenv("W3XRAY_CACHE_DIR", str(tmp_path))
        li._active_pid["pid"] = 4242
        try:
            try:
                raise RuntimeError("表面症状")
            except RuntimeError as ex:
                suffix = li.log_live_exception("test_stage", ex)
        finally:
            li._active_pid["pid"] = None
        log = tmp_path / "live" / "errors-v1.log"
        assert log.exists()
        text = log.read_text(encoding="utf-8")
        assert "stage=test_stage" in text
        assert "pid=4242" in text
        assert "Traceback" in text and "表面症状" in text
        assert "诊断日志" in suffix and "errors-v1.log" in suffix

    def test_log_live_exception_fail_open(self, tmp_path, monkeypatch):
        """日志写失败不抛出, 返回空后缀 (fail-open 不影响探测)。"""
        import w3xtool.cache_root as cr

        def boom():
            raise OSError("cache root unavailable")

        monkeypatch.setattr(cr, "w3xray_cache_root", boom)
        try:
            raise ValueError("x")
        except ValueError as ex:
            assert li.log_live_exception("s", ex) == ""

    def test_verify_opened_process_branches(self, monkeypatch):
        """身份复核四分支: 相同(大小写不敏感)/已变/无法判定不虚报。"""
        import w3xtool.live_inventory as inv

        h = object()
        monkeypatch.setattr(inv, "_process_identity", lambda handle: None)
        assert li.verify_opened_process(h, "C:/game/war3.exe") is None
        monkeypatch.setattr(inv, "_process_identity", lambda handle: "C:/GAME/War3.EXE")
        assert li.verify_opened_process(h, "C:/game/war3.exe") is None
        monkeypatch.setattr(
            inv, "_process_identity", lambda handle: "C:/other/notepad.exe"
        )
        warn = li.verify_opened_process(h, "C:/game/war3.exe")
        assert warn is not None and "war3.exe" in warn and "notepad.exe" in warn

    def test_detect_version_modules_seen_on_miss(self, monkeypatch, tmp_path):
        """Game.dll 未命中时 modules_seen 列出实际模块; 命中时不出现。"""
        import w3xtool.live_inventory as inv

        monkeypatch.setattr(
            inv, "enum_modules", lambda h: [("C:/x/notepad.exe", 0x400000)]
        )
        info = inv.detect_version(object())
        assert info["game_dll"] is None
        assert info["modules_seen"] == ["notepad.exe"]
        dll = tmp_path / "Game.dll"
        dll.write_bytes(b"MZ" + bytes(64))
        monkeypatch.setattr(
            inv,
            "enum_modules",
            lambda h: [("C:/x/notepad.exe", 0x400000), (str(dll), 0x600000)],
        )
        monkeypatch.setattr(inv, "read_file_version", lambda p: "1.27.0.52240")
        monkeypatch.setattr(inv, "pe_machine", lambda p: 0x014C)
        info2 = inv.detect_version(object())
        assert info2["game_dll"] is not None
        assert "modules_seen" not in info2
        assert info2["version"] == "1.27.0.52240"

    def test_derive_offsets_ambiguity_tagged(self, monkeypatch):
        """derive 多解: 多个候选过严格校验 → source 带歧义标注 + 地址序首个。"""
        import struct as _struct

        import w3xtool.live_handle_chain as hc

        base = 0x20000000
        buf = bytearray(0x1000)
        _struct.pack_into("<I", buf, 0x100, 0x10000000)  # vmctx 候选 1 (低地址)
        _struct.pack_into("<I", buf, 0x200, 0x10000000)  # 候选 2
        _struct.pack_into("<I", buf, 0x300, 0x10000000)  # 候选 3
        reader = hc.MemoryReader([(base, bytes(buf))])
        monkeypatch.setattr(hc, "_looks_like_handle_manager", lambda *a, **k: True)
        monkeypatch.setattr(hc, "_selection_chain_valid", lambda *a, **k: True)

        class FakeSystem:
            valid = True

            def __init__(self, *a, **k):
                pass

        monkeypatch.setattr(hc, "HandleSystem", FakeSystem)
        stages = []
        result = hc.derive_offsets(reader, base, base + 0x1000, on_stage=stages.append)
        assert result is not None
        assert "多解歧义: 3" in result.source
        assert result.vmctx_global_rva == 0x100  # 地址序首个, 非静默任选
        names = [s.name for s in stages]
        assert names[0] == "candidates" and names[-1] == "complete"

    def test_profile_from_dict_shape_validation(self):
        """形状校验 (学 trainer game_profile): 浮点/坏版本/未知键导入时拒。"""
        import pytest

        # 浮点 rva 静默截断 = 静默错值, 必须导入时拒绝
        with pytest.raises(ValueError, match=r"checks\[0\]\.rva"):
            lh.profile_from_dict(
                {
                    "game_version": "1.27.0.52240",
                    "checks": [{"rva": 12.5, "bytes": "90"}],
                }
            )
        # 版本号必须四段数字
        with pytest.raises(ValueError, match="四段"):
            lh.profile_from_dict({"game_version": "1.27"})
        # handle_chain 未知键给友好错误而非裸 TypeError
        with pytest.raises(ValueError, match="handle_chain"):
            lh.profile_from_dict(
                {
                    "game_version": "1.27.0.52240",
                    "handle_chain": {"no_such_field": 1},
                }
            )

    def test_profile_to_dict_without_chain(self):
        import json

        p = lh.resolve_profile("1.24.4.7138")
        d = json.loads(json.dumps(lh.profile_to_dict(p)))
        assert "handle_chain" not in d
        assert lh.profile_from_dict(d).handle_chain is None

    def test_check_failure_message_carries_domain(self):
        reader = self._reader_at(b"\x90" * 64)
        p = lh.LiveBuildProfile(
            version="t",
            engine="classic",
            arch="x86",
            game_struct_rva=None,
            unit_list_rva=None,
            handle_chain=None,
            tier="exact",
            source="t",
            checks=(lh.ProfileCheck(rva=8, expect=b"\x01\x02", label="w"),),
        )
        ok, fails = lh.verify_profile(reader, BASE, p)
        assert not ok
        assert fails[0].startswith("[text] w@0x8")

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


class TestDeriveStages:
    def test_stage_table_shape(self):
        from w3xtool.live_handle_chain import DERIVE_STAGES

        order = [
            "candidates",
            "build-systems",
            "strict-verify",
            "loose-verify",
            "complete",
        ]
        assert list(DERIVE_STAGES) == order
        assert all(s.message for s in DERIVE_STAGES.values())

    def test_success_reaches_complete_without_loose(self):
        from w3xtool.live_handle_chain import derive_offsets

        blob = bytearray(0x40000)
        struct.pack_into("<I", blob, 0x100, 0xFFFFFFFE)
        struct.pack_into("<I", blob, 0x108, BASE + 0x400)
        reader = lh.MemoryReader([(BASE, bytes(blob))])
        stages = []
        result = derive_offsets(reader, BASE, BASE + 0x40000, on_stage=stages.append)
        names = [s.name for s in stages]
        if result is not None:
            assert names[-1] == "complete"
            assert "loose-verify" not in names
        assert names[0] == "candidates"

    def test_stage_messages_are_progress_worthy(self):
        from w3xtool.live_handle_chain import DERIVE_STAGES

        for s in DERIVE_STAGES.values():
            assert s.name and s.message
            assert s.message != s.name


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
            "pid": 12345,
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
        assert entry["pid"] == 12345
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
