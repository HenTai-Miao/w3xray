"""GUI rendering for immutable icon-gap projections."""

from tests.gui_base import GuiTestCase
from w3xtool.api import MapData
from w3xtool.icon_evidence_index import IconEvidenceIndex
from w3xtool.icon_evidence_models import IconGapReason, UnresolvedIconEvidence
from w3xtool.icon_resources import IconObjectReference


class IconGapGuiTest(GuiTestCase):
    def test_map_gap_tab_shows_strict_unresolved_row(self) -> None:
        # Given
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
