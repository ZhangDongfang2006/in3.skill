"""坑层纯函数单测：chunk_material_ids + matched_filter_values + dedup_by。"""
import pytest

from in3_client.gotchas import chunk_material_ids, dedup_by, matched_filter_values


def test_chunk_80_is_one_block():
    ids = [str(i) for i in range(80)]
    chunks = chunk_material_ids(ids, 80)
    assert len(chunks) == 1
    assert chunks[0] == ids


def test_chunk_81_is_two_blocks():
    ids = [str(i) for i in range(81)]
    chunks = chunk_material_ids(ids, 80)
    assert len(chunks) == 2
    assert len(chunks[0]) == 80 and len(chunks[1]) == 1


def test_chunk_160_is_two_blocks():
    ids = [str(i) for i in range(160)]
    chunks = chunk_material_ids(ids, 80)
    assert [len(c) for c in chunks] == [80, 80]


def test_chunk_empty_is_no_blocks():
    assert chunk_material_ids([], 80) == []


def test_chunk_default_size_is_80():
    ids = [str(i) for i in range(81)]
    assert len(chunk_material_ids(ids)) == 2


def test_matched_filter_values_is_intersection():
    items = [{"material_id": "a"}, {"material_id": "b"}, {"material_id": "z"}]
    requested = ["a", "b", "c"]
    matched = matched_filter_values(items, requested, key="material_id")
    # 后端返回 a,b,z；请求 a,b,c → 交集 a,b（z 是后端多返的并集项，c 未匹配）
    assert set(matched) == {"a", "b"}


def test_matched_filter_values_empty():
    assert matched_filter_values([], ["a"], key="material_id") == []


def test_dedup_by_composite_key_keeps_first():
    items = [
        {"material_id": "a", "plant_no": "1", "v": 1},
        {"material_id": "a", "plant_no": "1", "v": 2},  # 重复键 → 丢
        {"material_id": "a", "plant_no": "2", "v": 3},  # 不同 plant → 保
    ]
    out = dedup_by(items, ("material_id", "plant_no"))
    assert len(out) == 2
    assert out[0]["v"] == 1 and out[1]["v"] == 3
