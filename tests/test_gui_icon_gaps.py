"""GUI rendering for immutable icon-gap projections."""

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import (
    IconDiagnosticFlag,
    IconGapReason,
    UnresolvedIconEvidence,
)
from w3xtool.icon_evidence_query import IconGapViewRow
from w3xtool.icon_resources import IconObjectReference
from w3xtool.extraction_ledger import build_extraction_ledger
from w3xtool.map_data import GameObject


class IconGapGuiTest(GuiTestCase):
    def test_each_visible_filter_restricts_batch_rows(self) -> None:
        # Given
        _reset_icon_gap_controls(self.app)
        rows = (
            IconGapViewRow(
                "one",
                "/maps/a.w3x",
                "a" * 64,
                "historical_client_miss",
                "物品",
                "I001",
                "one",
                "存在原始块",
                1,
                False,
                False,
                None,
                "one",
            ),
            IconGapViewRow(
                "two",
                "/maps/a.w3x",
                "a" * 64,
                "named_resource_missing",
                "技能",
                "A001",
                "two",
                "完整",
                1,
                False,
                False,
                None,
                "two",
            ),
            IconGapViewRow(
                "three",
                "/maps/a.w3x",
                "a" * 64,
                "named_resource_missing",
                "物品",
                "I002",
                "three",
                "存在损坏块",
                1,
                False,
                False,
                None,
                "three",
            ),
        )
        self.app._set_batch_icon_gaps(rows)
        self.app.icon_gap_scope.set("批量结果")

        # When / Then
        self.app.icon_gap_reason.set("historical_client_miss")
        self.app._refresh_icon_gaps()
        assert tuple(self.app.icon_gap_rows) == ("one",)
        self.app.icon_gap_reason.set("全部")
        self.app.icon_gap_category.set("物品")
        self.app._refresh_icon_gaps()
        assert set(self.app.icon_gap_rows) == {"one", "three"}
        self.app.icon_gap_category.set("全部")
        self.app.icon_gap_archive.set("存在损坏块")
        self.app._refresh_icon_gaps()
        assert tuple(self.app.icon_gap_rows) == ("three",)

    def test_filters_and_candidate_mode_only_show_selected_exact_rows(self) -> None:
        # Given
        _reset_icon_gap_controls(self.app)
        md = _map_with_gap_rows()
        self.app._render_map(md, [], [], None)

        # When
        self.app.icon_gap_reason.set("historical_client_miss")
        self.app.icon_gap_category.set("物品")
        self.app.icon_gap_archive.set("存在原始块")
        self.app._refresh_icon_gaps()

        # Then
        assert len(self.app.icon_gap_tree.get_children()) == 1
        candidate = IconGapViewRow(
            "candidate",
            "",
            "a" * 64,
            "exact_other_map_path",
            "",
            "",
            r"Custom\BTNBlade.blp",
            "",
            0,
            True,
            False,
            None,
            "候选未采用",
        )
        self.app._set_batch_icon_gaps((candidate,))
        self.app.icon_gap_scope.set("批量结果")
        self.app.icon_gap_mode.set("候选（未采用）")
        self.app._refresh_icon_gaps()
        row = self.app.icon_gap_rows["candidate"]
        assert row.adopted is False
        assert self.app.icon_gap_open_button.cget("state") == "disabled"

    def test_scope_preserves_batch_rows_and_blocks_cross_map_navigation(self) -> None:
        # Given
        _reset_icon_gap_controls(self.app)
        md = _map_with_gap_rows()
        obj = GameObject("物品", "w3t", "I001", "I001", "当前物品", True)
        md.obj_identity_index[("物品", "I001")] = obj
        self.app._render_map(md, [], [], None)
        foreign = IconGapViewRow(
            "foreign",
            "/maps/other.w3x",
            "b" * 64,
            "named_resource_missing",
            "物品",
            "I001",
            r"Custom\BTNOther.blp",
            "完整",
            1,
            False,
            False,
            ("物品", "I001"),
            "foreign",
        )

        # When
        self.app._set_batch_icon_gaps((foreign,))
        self.app.icon_gap_scope.set("批量结果")
        self.app._refresh_icon_gaps()
        self.app.icon_gap_tree.selection_set("foreign")
        self.app._show_icon_gap_evidence()

        # Then
        assert self.app.icon_gap_open_button.cget("state") == "disabled"
        self.app._render_map(md, [], [], None)
        self.app.icon_gap_scope.set("批量结果")
        self.app._refresh_icon_gaps()
        assert "foreign" in self.app.icon_gap_rows
        self.app.icon_gap_scope.set("当前地图")
        self.app._refresh_icon_gaps()
        assert "foreign" not in self.app.icon_gap_rows
        same = IconGapViewRow(
            "same",
            md.path,
            "a" * 64,
            "named_resource_missing",
            "物品",
            "I001",
            r"Custom\BTNSame.blp",
            "完整",
            1,
            False,
            False,
            ("物品", "I001"),
            "same",
        )
        self.app._set_batch_icon_gaps((same,))
        self.app.icon_gap_scope.set("批量结果")
        self.app._refresh_icon_gaps()
        self.app.icon_gap_tree.selection_set("same")
        self.app._show_icon_gap_evidence()
        assert self.app.icon_gap_open_button.cget("state") == "normal"

    def test_map_gap_tab_shows_strict_unresolved_row(self) -> None:
        # Given
        _reset_icon_gap_controls(self.app)
        md = MapData("map.w3x", "图标缺口图")
        md.icon_evidence = IconEvidenceIndex.build(
            unresolved=(
                UnresolvedIconEvidence(
                    IconObjectReference(
                        "物品",
                        "I001",
                        "烈焰剑",
                        map_path="map.w3x",
                        map_sha256="a" * 64,
                        field_key="iico",
                        normalized_path=r"Custom\BTNBlade.blp",
                    ),
                    IconGapReason.HISTORICAL_CLIENT_MISS,
                    (),
                    (),
                ),
            )
        )

        # When
        self.app._render_map(md, [], [], None)
        self.app.tabs.set("图标缺口")
        self.app.update_idletasks()

        # Then
        rows = self.app.icon_gap_tree.get_children()
        assert len(rows) == 1
        assert (
            self.app.icon_gap_tree.item(rows[0], "values")[0]
            == "historical_client_miss"
        )


def _map_with_gap_rows() -> MapData:
    md = MapData("/maps/current.w3x", "图标缺口图")
    md.extraction_ledger = build_extraction_ledger(md.path, "a" * 64, ())
    md.icon_evidence = IconEvidenceIndex.build(
        unresolved=(
            UnresolvedIconEvidence(
                IconObjectReference(
                    "物品",
                    "I001",
                    "烈焰剑",
                    map_path=md.path,
                    map_sha256="a" * 64,
                    field_key="iico",
                    normalized_path=r"Custom\BTNBlade.blp",
                ),
                IconGapReason.HISTORICAL_CLIENT_MISS,
                (IconDiagnosticFlag.ARCHIVE_HAS_RAW_BLOCK,),
                (),
            ),
        )
    )
    return md


def _reset_icon_gap_controls(app) -> None:
    app.icon_gap_scope.set("当前地图")
    app.icon_gap_mode.set("未解析")
    app.icon_gap_reason.set("全部")
    app.icon_gap_category.set("全部")
    app.icon_gap_archive.set("全部")
