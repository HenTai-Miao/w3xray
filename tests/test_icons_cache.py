"""游戏 MPQ 进程级缓存：同一路径只打开/解析一次，跨地图复用。

游戏 war3.mpq 等是几十~上百 MB 的大档且不随地图变化，
每次打开地图都重开会重复扫头+解密表，缓存后复用同一实例。
"""
import os
import struct
import tempfile
import unittest

from w3xtool.icons import _open_game_mpq, _GAME_MPQ_CACHE, IconResolver

_WAR3 = r"C:\Program Files (x86)\Warcraft III\war3\war3.mpq"


def _write_min_mpq():
    hdr = struct.pack("<4sIIHHIIII", b"MPQ\x1a", 0x20, 0, 0, 3, 32, 96, 4, 1)
    buf = bytearray(112)
    buf[0:len(hdr)] = hdr
    fd, path = tempfile.mkstemp(suffix=".w3x")
    os.close(fd)
    with open(path, "wb") as f:
        f.write(buf)
    return path


class TestGameMpqCache(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(_WAR3), "需要真实 war3.mpq")
    def test_same_path_returns_same_instance(self):
        a = _open_game_mpq(_WAR3)
        b = _open_game_mpq(_WAR3)
        self.assertIsNotNone(a)
        self.assertIs(a, b)               # 第二次命中缓存，复用同一实例
        self.assertIn(_WAR3, _GAME_MPQ_CACHE)


class TestIconResolverLifecycle(unittest.TestCase):
    def test_extra_paths_not_added_to_global_cache(self):
        # 战役 .w3n 额外档不应进入进程级游戏缓存(否则浏览大量战役会永不释放 → 内存泄漏)
        path = _write_min_mpq()
        try:
            r = IconResolver(path, extra_paths=[path])
            self.assertNotIn(path, _GAME_MPQ_CACHE)
            self.assertEqual(len(r.extra), 1)
            r.close()
        finally:
            os.remove(path)

    def test_close_releases_map_and_is_idempotent(self):
        path = _write_min_mpq()
        try:
            r = IconResolver(path, extra_paths=[path])
            r.close()
            r.close()                      # 幂等
        finally:
            os.remove(path)


if __name__ == "__main__":
    unittest.main()
