"""游戏 MPQ 进程级缓存：同一路径只打开/解析一次，跨地图复用。

游戏 war3.mpq 等是几十~上百 MB 的大档且不随地图变化，
每次打开地图都重开会重复扫头+解密表，缓存后复用同一实例。
"""
import os
import unittest

from w3xtool.icons import _open_game_mpq, _GAME_MPQ_CACHE

_WAR3 = r"C:\Program Files (x86)\Warcraft III\war3\war3.mpq"


class TestGameMpqCache(unittest.TestCase):
    @unittest.skipUnless(os.path.exists(_WAR3), "需要真实 war3.mpq")
    def test_same_path_returns_same_instance(self):
        a = _open_game_mpq(_WAR3)
        b = _open_game_mpq(_WAR3)
        self.assertIsNotNone(a)
        self.assertIs(a, b)               # 第二次命中缓存，复用同一实例
        self.assertIn(_WAR3, _GAME_MPQ_CACHE)


if __name__ == "__main__":
    unittest.main()
