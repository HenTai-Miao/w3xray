"""war3map world metadata: regions, cameras, and sounds."""

import struct
import unittest

from w3xtool.w3world import parse_cameras, parse_regions, parse_sounds


def _i(v):
    return struct.pack("<i", v)


def _f(v):
    return struct.pack("<f", v)


def _z(s):
    return s.encode("utf-8") + b"\x00"


def _region(name="区域A"):
    return (
        _f(-128.0) + _f(-64.0) + _f(128.0) + _f(64.0)
        + _z(name) + _i(7) + b"RLhr" + _z("Sound\\Rain.wav")
        + bytes([30, 20, 10, 255])
    )


def _camera(name="镜头A", local=False):
    values = [10.0, 20.0, 0.0, 90.0, 304.0, 1650.0, 0.0, 70.0, 5000.0, 100.0]
    if local:
        values.extend([1.0, 2.0, 3.0])
    return b"".join(_f(v) for v in values) + _z(name)


def _sound_v1(name="击杀声"):
    return (
        _z(name) + _z("Sound\\kill.wav") + _z("DefaultEAXON")
        + _i(1 | 2 | 8) + _i(100) + _i(200) + _i(127)
        + _f(1.0) + _i(0) + _i(0) + _i(0)
        + _f(100.0) + _f(1000.0) + _f(3000.0)
        + _i(0) + _i(0) + _i(0) + _i(0) + _i(0) + _i(0)
    )


def _sound_v3(name="导入声"):
    return (
        _z(name) + _z("war3mapImported\\voice.wav") + _z("DefaultEAXON")
        + _i(16 | 8) + _i(10) + _i(20) + _i(100)
        + _f(1.0) + _f(0.25) + _i(5) + _i(2)
        + _f(200.0) + _f(900.0) + _f(1800.0)
        + _i(0) + _i(0) + _i(127) + _i(0) + _i(0) + _i(0)
        + _z("gg_snd_voice") + _z("") + _z("war3mapImported\\voice.wav")
        + _i(-1) + bytes([0]) + _i(-1) + _i(0) + _i(0) + bytes([0]) + _i(1)
    )


class TestParseRegions(unittest.TestCase):
    def test_region_fields_and_trigstr(self):
        data = _i(5) + _i(1) + _region("TRIGSTR_001")
        regions = parse_regions(data, {1: "出生区域"})
        self.assertEqual(len(regions), 1)
        self.assertEqual(regions[0].name, "出生区域")
        self.assertEqual(regions[0].region_id, 7)
        self.assertEqual(regions[0].weather_effect, "RLhr")
        self.assertEqual(regions[0].color_rgb, (10, 20, 30))

    def test_bad_region_data_returns_empty(self):
        self.assertEqual(parse_regions(b""), [])
        self.assertEqual(parse_regions(_i(99) + _i(1)), [])


class TestParseCameras(unittest.TestCase):
    def test_old_camera_layout(self):
        cameras = parse_cameras(_i(0) + _i(1) + _camera("开场镜头"))
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].name, "开场镜头")
        self.assertAlmostEqual(cameras[0].target_x, 10.0)
        self.assertIsNone(cameras[0].local_pitch)

    def test_new_camera_layout_with_local_rotation(self):
        cameras = parse_cameras(_i(0) + _i(1) + _camera("新版镜头", local=True))
        self.assertEqual(len(cameras), 1)
        self.assertEqual(cameras[0].name, "新版镜头")
        self.assertAlmostEqual(cameras[0].local_pitch, 1.0)
        self.assertAlmostEqual(cameras[0].local_yaw, 2.0)

    def test_bad_camera_data_returns_empty(self):
        self.assertEqual(parse_cameras(b"bad"), [])


class TestParseSounds(unittest.TestCase):
    def test_v1_sound_flags(self):
        sounds = parse_sounds(_i(1) + _i(1) + _sound_v1())
        self.assertEqual(len(sounds), 1)
        self.assertEqual(sounds[0].name, "击杀声")
        self.assertTrue(sounds[0].is_looping)
        self.assertTrue(sounds[0].is_3d)
        self.assertTrue(sounds[0].is_music)
        self.assertFalse(sounds[0].is_imported)

    def test_v3_sound_extra_fields(self):
        sounds = parse_sounds(_i(3) + _i(1) + _sound_v3())
        self.assertEqual(len(sounds), 1)
        self.assertEqual(sounds[0].variable_name, "gg_snd_voice")
        self.assertTrue(sounds[0].is_imported)
        self.assertTrue(sounds[0].is_music)

    def test_bad_sound_data_returns_empty(self):
        self.assertEqual(parse_sounds(_i(3) + _i(999999999)), [])


class _FakeArchive:
    def __init__(self, files):
        self._files = files

    def has_file(self, name):
        return name in self._files

    def read_file(self, name):
        return self._files[name]


class TestWorldMetadataIntegration(unittest.TestCase):
    def test_add_world_metadata_fills_mapdata(self):
        from w3xtool.api import MapData
        from w3xtool.map_extras import add_world_metadata
        md = MapData(path="x", name="x")
        arch = _FakeArchive({
            "war3map.w3r": _i(5) + _i(1) + _region(),
            "war3map.w3c": _i(0) + _i(1) + _camera(),
            "war3map.w3s": _i(1) + _i(1) + _sound_v1(),
        })
        add_world_metadata(md, arch, {})
        self.assertEqual(len(md.regions), 1)
        self.assertEqual(len(md.cameras), 1)
        self.assertEqual(len(md.sounds), 1)


if __name__ == "__main__":
    unittest.main()
