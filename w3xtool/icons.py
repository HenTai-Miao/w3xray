"""图标解析：按 Art/图标 路径，从地图内或游戏 MPQ 取 BLP 并解码成 PIL 图。

地图自定义图标在地图 MPQ 里；基础图标在游戏 war3.mpq 等里（大档用 mmap，不爆内存）。
"""
from __future__ import annotations

import os

from .game_data_source import GameDataSource, open_game_data_source
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
    def __init__(self, map_path: str, extra_paths=None, game_data_path: str | None = None):
        self.map_path = map_path
        try:
            self.map = MPQArchive(map_path)
        except Exception:  # noqa: BROAD_EXCEPT_OK - invalid optional map keeps icon lookup usable.
            self.map = None
        # 额外档（如战役 .w3n 顶层，子图图标常放那里）。**不**进进程级游戏缓存：
        # 那是给固定几个 war3*.mpq 大档用的；战役档各不相同，进了缓存就永不释放(内存泄漏)。
        # 这些随本 resolver 生命周期，close() 时一并关闭。
        self.extra = []
        for p in (extra_paths or []):
            try:
                self.extra.append(MPQArchive(p))
            except Exception:  # noqa: BROAD_EXCEPT_OK - skip unreadable optional campaign archives.
                continue
        self.game_dir = find_game_dir(map_path)
        self.game_data_source = _open_game_data_source(game_data_path)
        self._game = None
        self._cache = {}     # path.lower() -> PIL.Image | None

    def close(self):
        """释放本 resolver 独占的档(地图档 + 战役额外档)。可重复调用。

        游戏大档(self._game)是进程级共享缓存，不在此关闭。
        """
        for arch in [self.map] + self.extra:
            if arch is not None:
                try:
                    arch.close()
                except Exception:  # noqa: BROAD_EXCEPT_OK - close every remaining optional archive.
                    continue
        self.map = None
        self.extra = []
        close_game_data = getattr(self.game_data_source, "close", None)
        if callable(close_game_data):
            try:
                close_game_data()
            except OSError:
                self.game_data_source = None
        self.game_data_source = None
        self._cache = {}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    def _games(self):
        if self._game is None:
            self._game = []
            if self.game_dir:
                for n in _GAME_MPQS:
                    p = os.path.join(self.game_dir, n)
                    if os.path.exists(p):
                        try:
                            self._game.append(_open_game_mpq(p))
                        except Exception:  # noqa: BROAD_EXCEPT_OK - skip invalid optional game archives.
                            continue
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
        archives = ([self.map] if self.map else []) + self.extra
        if self.game_data_source is not None:
            archives.append(self.game_data_source)
        archives += self._games()
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
                except MemoryError:
                    raise                 # 内存耗尽不可吞：暴露出来而非伪装成"无图标"
                except Exception:  # noqa: BROAD_EXCEPT_OK - one corrupt icon candidate must not stop lookup.
                    continue
        return None


def _open_game_data_source(path: str | None) -> GameDataSource | None:
    return open_game_data_source(path)
