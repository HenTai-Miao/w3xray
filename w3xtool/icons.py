"""图标解析：按 Art/图标 路径，从地图内或游戏 MPQ 取 BLP 并解码成 PIL 图。

地图自定义图标在地图 MPQ 里；基础图标在游戏 war3.mpq 等里（大档用 mmap，不爆内存）。
"""
from __future__ import annotations

import os

from .mpq import MPQArchive
from .blp import decode_blp

_GAME_MPQS = ["War3Patch.mpq", "War3xLocal.mpq", "War3x.mpq", "war3.mpq"]

# 游戏 MPQ 进程级缓存：这些大档不随地图变化，跨地图复用同一实例，
# 避免每次打开地图都重新扫头+解密表。
_GAME_MPQ_CACHE = {}


def _open_game_mpq(path: str):
    arch = _GAME_MPQ_CACHE.get(path)
    if arch is None:
        arch = MPQArchive(path)
        _GAME_MPQ_CACHE[path] = arch
    return arch


def find_game_dir(start_path: str):
    d = os.path.dirname(os.path.abspath(start_path))
    for _ in range(7):
        if os.path.exists(os.path.join(d, "war3.mpq")):
            return d
        nd = os.path.dirname(d)
        if nd == d:
            break
        d = nd
    for cand in [r"C:\Program Files (x86)\Warcraft III\war3",
                 r"C:\Program Files\Warcraft III\war3"]:
        if os.path.exists(os.path.join(cand, "war3.mpq")):
            return cand
    return None


class IconResolver:
    def __init__(self, map_path: str, extra_paths=None):
        self.map_path = map_path
        try:
            self.map = MPQArchive(map_path)
        except Exception:
            self.map = None
        # 额外档（如战役 .w3n 顶层，子图图标常放那里）；用进程级缓存避免反复打开
        self.extra = []
        for p in (extra_paths or []):
            try:
                self.extra.append(_open_game_mpq(p))
            except Exception:
                pass
        self.game_dir = find_game_dir(map_path)
        self._game = None
        self._cache = {}     # path.lower() -> PIL.Image | None

    def _games(self):
        if self._game is None:
            self._game = []
            if self.game_dir:
                for n in _GAME_MPQS:
                    p = os.path.join(self.game_dir, n)
                    if os.path.exists(p):
                        try:
                            self._game.append(_open_game_mpq(p))
                        except Exception:
                            pass
        return self._game

    def get_image(self, path: str):
        if not path:
            return None
        key = path.lower()
        if key in self._cache:
            return self._cache[key]
        img = self._load(path)
        self._cache[key] = img
        return img

    def _load(self, path: str):
        p = path.replace("/", "\\").strip().strip('"')
        if not p:
            return None
        base = p.rsplit(".", 1)[0] if "." in p.rsplit("\\", 1)[-1] else p
        candidates = [p, base + ".blp", base + ".tga", base + ".dds"]
        # 去重保序
        seen = set(); cands = [c for c in candidates if not (c in seen or seen.add(c))]
        archives = ([self.map] if self.map else []) + self.extra + self._games()
        for arch in archives:
            if not arch:
                continue
            for c in cands:
                try:
                    if arch.has_file(c):
                        data = arch.read_file(c)
                        img = decode_blp(data)
                        if img is not None:
                            return img
                except Exception:
                    continue
        return None
