"""Campaign overview query exports contain the complete loaded child family."""

from __future__ import annotations

from pathlib import Path

import pytest

from gametool.api import load_map
from gametool.extraction_profile import ExtractionProfile, normalize_profile
import gametool.gui_export_actions as exports
import gametool.gui_pack_query as query_gui
from gametool.knowledge_results import KnowledgeWriteItem, KnowledgeWriteReport
from gametool.pack_query_cli import PackQueryCliOptions, execute_pack_query
from tests.test_release_gui_actions import _ActionHost


_CAMPAIGN = (
    Path(__file__).parent
    / "fixtures"
    / "reference"
    / "stormlib-reference-parity-campaign.w3n"
)


def test_campaign_overview_auto_query_exports_and_queries_child_tables(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    campaign = load_map(str(_CAMPAIGN))
    host = _ActionHost()
    host.map_data = campaign
    root = tmp_path / "campaign-pack"
    opened: list[str | None] = []
    monkeypatch.setattr(exports, "tmp_extract_dir", lambda *_args, **_kwargs: str(root))
    monkeypatch.setattr(exports, "save_last_pack_dir", lambda _path: None)
    monkeypatch.setattr(
        query_gui,
        "open_pack_query_dialog",
        lambda _app, provider, _ensure, **_kwargs: opened.append(provider()),
    )
    try:
        assert campaign.category_counts() == {}
        assert len(campaign.sub_maps) == 1
        host.on_pack_query(prefill_command="list")
        host.pump()
        assert opened == [str(root)]

        result = execute_pack_query(PackQueryCliOptions(str(root), "list", ""))

        assert result.exit_code == 0, result.render(as_json=True)
        assert result.campaign
        assert any(
            "I001" in line for section in result.sections for line in section.lines
        )
        children = tuple((root / "子地图").iterdir())
        assert len(children) == len(campaign.sub_maps)
        assert (children[0] / "对象字段.tsv").is_file()
    finally:
        host._shutdown_gui_worker_host(1)
        campaign.close()


def test_automatic_query_uses_full_profile_and_manual_export_keeps_user_scope(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    selected = normalize_profile({"objects": False, "scripts": False})
    profiles: list[ExtractionProfile] = []
    report = KnowledgeWriteReport((KnowledgeWriteItem("地图信息.txt", True, 1, None),))

    def publish(_md, _out, **kwargs):
        profiles.append(kwargs["profile"])
        return report

    monkeypatch.setattr(exports, "load_profile", lambda: selected)
    monkeypatch.setattr(exports, "write_knowledge_pack_family_report", publish)
    monkeypatch.setattr(
        exports, "tmp_extract_dir", lambda *_args, **_kwargs: str(tmp_path)
    )
    monkeypatch.setattr(exports, "save_last_pack_dir", lambda _path: None)
    monkeypatch.setattr(
        query_gui, "open_pack_query_dialog", lambda *_args, **_kwargs: None
    )
    automatic = _ActionHost()
    manual = _ActionHost()
    monkeypatch.setattr(manual, "_show_pack_result", lambda *_args: None)
    try:
        automatic.on_pack_query(prefill_command="list")
        automatic.pump()
        manual.on_export_pack()
        manual.pump()

        assert profiles[0].disabled_categories() == ()
        assert profiles[1] == selected
        assert automatic.current_map_pack_dir() == str(tmp_path)
        assert manual.current_map_pack_dir() is None
    finally:
        automatic._shutdown_gui_worker_host(1)
        manual._shutdown_gui_worker_host(1)
