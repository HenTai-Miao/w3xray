"""地图内嵌 SLK 文件清单摘要。"""

from w3xtool.slkmeta import build_slk_inventory


def test_build_slk_inventory_reports_rows_and_columns():
    # Given: a map file set containing an embedded SLK object table.
    files = {
        "Units\\UnitData.slk": (
            b"ID\n"
            b"B;Y2;X3\n"
            b'C;X1;Y1;K"unitID"\n'
            b'C;X2;Y1;K"Name"\n'
            b'C;X3;Y1;K"HP"\n'
            b'C;X1;Y2;K"hfoo"\n'
            b'C;X2;Y2;K"Footman"\n'
            b"C;X3;Y2;K420\n"
        ),
        "war3map.j": b"function main takes nothing returns nothing\nendfunction\n",
    }

    # When: the SLK inventory is built.
    report = build_slk_inventory(files)

    # Then: only SLK files are summarized with useful dimensions.
    assert len(report.files) == 1
    assert report.files[0].path == "Units\\UnitData.slk"
    assert report.files[0].rows == 1
    assert report.files[0].columns == 2


def test_build_slk_inventory_skips_invalid_slk_payloads():
    # Given: a broken SLK-like file with no parseable rows.
    files = {"Units\\UnitData.slk": b"not slk"}

    # When: the SLK inventory is built.
    report = build_slk_inventory(files)

    # Then: empty/unusable tables are ignored.
    assert report.files == ()
