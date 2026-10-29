# -*- coding: utf-8 -*-
"""_icon_paths_from_pack 的继承行/自定义行优先级回归测试。

对象字段.tsv 同一物品可能同时有 base: 继承图标行与自定义图标行；
自定义行必须获胜，且不得依赖 TSV 行序（此前靠排序碰巧正确）。
"""

from pathlib import Path

import pytest

pytest.importorskip("numpy")

from gametool.live_inventory import _icon_paths_from_pack  # noqa: E402 - numpy 未装时 importorskip 先退出


def _write_pack(tmp_path: Path, rows: list[str]) -> Path:
    pack = tmp_path / "pack"
    pack.mkdir()
    (pack / "对象字段.tsv").write_text(
        "".join(r + "\n" for r in rows), encoding="utf-8"
    )
    return pack


def test_custom_icon_beats_inherited_even_when_base_row_comes_later(tmp_path):
    pack = _write_pack(
        tmp_path,
        [
            "物品\tI0AA\t冰晶\tdisplay:icon\t图标\tCommandButtons\\BTNcustom.blp\twar3map.w3t",
            "物品\tI0AA\t冰晶\tbase:art\tart\tCommandButtons\\BTNbase.blp\tbase:shen",
        ],
    )
    assert _icon_paths_from_pack(pack) == {"I0AA": "CommandButtons/BTNcustom.blp"}


def test_inherited_icon_used_when_only_base_row_exists(tmp_path):
    pack = _write_pack(
        tmp_path,
        [
            "物品\tI0BB\t木盾\tbase:art\tart\tCommandButtons\\BTNwood.blp\tbase:shen",
        ],
    )
    assert _icon_paths_from_pack(pack) == {"I0BB": "CommandButtons/BTNwood.blp"}


def test_non_icon_and_malformed_rows_ignored(tmp_path):
    pack = _write_pack(
        tmp_path,
        [
            "物品\tI0CC\t说明行\tides\t描述\tCommandButtons\\BTNx.blp\twar3map.w3t",
            "物品",
            "单位\th0AA\t铁匠铺\tdisplay:icon\t图标\tCommandButtons\\BTNshop.blp\twar3map.w3u",
        ],
    )
    assert _icon_paths_from_pack(pack) == {}


@pytest.mark.parametrize("state", ["overridden", "conflict", "unknown"])
@pytest.mark.parametrize("raw_first", [True, False])
def test_unconfirmed_icon_evidence_does_not_replace_effective_icon(
    tmp_path, state, raw_first
):
    effective = "物品\tI0AA\t冰晶\tdisplay:icon\t图标\tCommandButtons/BTNcurrent.blp\twar3mapSkin.w3t\tconfirmed"
    raw = f"物品\tI0AA\t冰晶\tdisplay:icon\t图标\tCommandButtons/BTNold.blp\twar3map.w3t\t{state}"
    pack = _write_pack(
        tmp_path,
        [
            "分类\tID\t名称\t字段键\t字段名\t值\t来源\t证据状态",
            *([raw, effective] if raw_first else [effective, raw]),
        ],
    )
    assert _icon_paths_from_pack(pack) == {"I0AA": "CommandButtons/BTNcurrent.blp"}
