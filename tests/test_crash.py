"""地图崩溃风险静态检测。"""

from w3xtool.api import GameObject, MapData
from w3xtool.crash import build_crash_report


def test_detects_chain_lightning_negative_full_decay():
    # Given: a Chain Lightning ability with -100% per-target damage reduction.
    md = MapData(path="x.w3x", name="x")
    md.objects = {
        "技能": [
            GameObject(
                category="技能",
                ext="w3a",
                obj_id="A001",
                base_id="AOcl",
                name="闪电链",
                is_custom=True,
                fields=[("每个目标伤害减少", "-1.00")],
            )
        ]
    }

    # When: crash risks are scanned.
    report = build_crash_report(md)

    # Then: the known 1.24E-1.26 crash pattern is reported.
    item = report.by_code["crash.chain_lightning.full_negative_decay"]
    assert item.object_id == "A001"
    assert "1.24E" in item.detail


def test_ignores_safe_chain_lightning_decay():
    # Given: a Chain Lightning ability with normal positive reduction.
    md = MapData(path="x.w3x", name="x")
    md.objects = {
        "技能": [
            GameObject(
                category="技能",
                ext="w3a",
                obj_id="A001",
                base_id="AOcl",
                name="闪电链",
                is_custom=True,
                fields=[("每个目标伤害减少", "0.15")],
            )
        ]
    }

    # When: crash risks are scanned.
    report = build_crash_report(md)

    # Then: no crash risk is emitted.
    assert report.items == ()


def test_detects_game_cache_api_crash_risk():
    # Given: a script uses old game-cache storage APIs.
    md = MapData(path="x.w3x", name="x")
    md.scripts = {
        "war3map.j": (
            'set udg_cache = InitGameCache("mission.w3v")\n'
            'call StoreInteger(udg_cache, "MissionKey", "count", 1)\n'
            "call SaveGameCache(udg_cache)\n"
        )
    }

    # When: crash risks are scanned.
    report = build_crash_report(md)

    # Then: game-cache usage is reported for manual review.
    item = report.by_code["crash.game_cache.api"]
    assert item.source == "脚本 war3map.j"
    assert "游戏缓存" in item.detail
