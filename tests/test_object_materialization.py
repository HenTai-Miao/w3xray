"""多核物化与串行物化的结果一致性。"""

from __future__ import annotations

import pytest

from w3xtool.object_candidates import (
    ObjectCandidate,
    ObjectFieldValue,
    ObjectSourceKind,
)
from w3xtool.object_materialization import merge_object_candidates

NL = chr(10)


def _candidates(count: int) -> tuple[ObjectCandidate, ...]:
    values = tuple(
        ObjectFieldValue(
            "display:name",
            "名称",
            f"对象{index:03d}",
            "war3map.w3u",
            ObjectSourceKind.BINARY,
        )
        for index in range(count)
    )
    return tuple(
        ObjectCandidate(
            "单位",
            f"u{index:03d}",
            f"u{index:03d}",
            False,
            "war3map.w3u",
            (values[index],),
            (),
        )
        for index in range(count)
    )


def test_parallel_merge_matches_serial(monkeypatch: pytest.MonkeyPatch) -> None:
    # Given: 足量候选触发并行阈值。
    candidates = _candidates(80)

    # When: 串行与并行各跑一次。
    monkeypatch.setenv("W3XRAY_MATERIALIZE_WORKERS", "1")
    serial = merge_object_candidates(candidates, {})
    monkeypatch.setenv("W3XRAY_MATERIALIZE_WORKERS", "2")
    parallel = merge_object_candidates(candidates, {})

    # Then: 逐对象完全一致（物化是纯函数，并行只换执行方式）。
    assert serial == parallel
    assert len(parallel) == 80


def test_invalid_workers_value_falls_back_to_serial(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Given: 非法并行度配置。
    monkeypatch.setenv("W3XRAY_MATERIALIZE_WORKERS", "not-a-number")

    # When: 正常物化。
    result = merge_object_candidates(_candidates(4), {})

    # Then: 按串行完成，不抛异常。
    assert len(result) == 4
