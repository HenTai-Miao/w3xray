"""脚本诊断：异步/本地状态/JASS 风险调用的只读检测。"""
import unittest

from w3xtool.api import MapData
from w3xtool.diagnostics import DiagnosticSeverity, build_script_diagnostics


class ScriptDiagnosticsTest(unittest.TestCase):
    def test_get_local_player_is_warning(self):
        # Given: script branches on GetLocalPlayer.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "if GetLocalPlayer() == Player(0) then\nendif"}

        # When: diagnostics are built.
        report = build_script_diagnostics(md)

        # Then: the local-player branch is reported.
        item = report.by_code["script.get_local_player"]
        self.assertEqual(item.severity, DiagnosticSeverity.WARNING)
        self.assertIn("GetLocalPlayer", item.detail)

    def test_sync_mutation_inside_get_local_player_branch_is_warning(self):
        # Given: a local-player branch mutates synchronized game state.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {
            "war3map.j": (
                "if GetLocalPlayer() == Player(0) then\n"
                "    call CreateUnit(Player(0), 'hfoo', 0, 0, 0)\n"
                "endif\n"
            )
        }

        # When: diagnostics are built.
        report = build_script_diagnostics(md)

        # Then: the higher-risk local sync mutation is reported separately.
        item = report.by_code["script.get_local_player.sync_mutation"]
        self.assertEqual(item.severity, DiagnosticSeverity.WARNING)
        self.assertIn("CreateUnit", item.detail)

    def test_camera_state_getter_is_warning(self):
        # Given: script reads local camera state.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "set x = GetCameraTargetPositionX()"}

        # When: diagnostics are built.
        report = build_script_diagnostics(md)

        # Then: camera-state access is reported.
        self.assertIn("script.local_state.camera", report.by_code)

    def test_dz_api_is_warning(self):
        # Given: script uses a Dz API often tied to local client state.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "call DzTriggerRegisterMouseEvent(trig, 1, 1)"}

        # When: diagnostics are built.
        report = build_script_diagnostics(md)

        # Then: Dz API usage is reported.
        self.assertIn("script.dz_api", report.by_code)

    def test_plain_script_has_no_warnings(self):
        # Given: a simple deterministic script.
        md = MapData(path="x.w3x", name="x")
        md.scripts = {"war3map.j": "function main takes nothing returns nothing\nendfunction"}

        # When: diagnostics are built.
        report = build_script_diagnostics(md)

        # Then: no warning is emitted.
        self.assertEqual(report.warnings, ())


if __name__ == "__main__":
    unittest.main()
