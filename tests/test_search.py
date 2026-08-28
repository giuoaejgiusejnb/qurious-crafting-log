import random

import pytest

from app.core.importer import import_block
from app.core.search import SearchParams, fetch_distinct_labels, fetch_skill_breakdown, search_results
from app.core.skill_registry import SkillRegistry
from app.db.connection import get_connection
from tests.helpers import build_row


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def _allowed_ids(conn, names=("攻撃", "見切り", "弱点特効")):
    registry = SkillRegistry(conn)
    return registry.get_ids(list(names))


def test_search_includes_result_reaching_threshold_via_two_different_skills(conn):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1), ("見切り", 1)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2)
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [1]


def test_search_includes_result_reaching_threshold_via_single_skill_level(conn):
    # 「攻撃+2」は「攻撃+1が2個」と同じ扱いなので、しきい値2を満たす
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2)
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [1]


def test_search_excludes_result_below_threshold(conn):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2)
    rows = search_results(conn, params)

    assert rows == []


def test_search_does_not_exclude_result_with_skill_outside_allowed_set(conn):
    # 現仕様: 許可集合外のスキル（爆破）を含んでいても、許可集合内の合計がしきい値を
    # 満たしていれば除外しない（旧仕様の「集合外を含むと除外」ルールは廃止）
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1), ("見切り", 1), ("爆破", 1)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2)
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [1]


def test_search_threshold_controls_how_many_matches_are_required(conn):
    text = "\n".join(
        [
            build_row(zeny_count=1, skills=[("攻撃", 2), ("見切り", 2)]),  # 許可集合内合計4
            build_row(zeny_count=2, skills=[("攻撃", 2), ("見切り", 1)]),  # 許可集合内合計3
            build_row(zeny_count=3, skills=[("攻撃", 1), ("見切り", 1)]),  # 許可集合内合計2
        ]
    )
    import_block(conn, text)
    allowed = _allowed_ids(conn)

    assert sorted(r.zeny_count for r in search_results(conn, SearchParams(allowed_skill_ids=allowed, threshold=4))) == [1]
    assert sorted(r.zeny_count for r in search_results(conn, SearchParams(allowed_skill_ids=allowed, threshold=3))) == [1, 2]
    assert sorted(r.zeny_count for r in search_results(conn, SearchParams(allowed_skill_ids=allowed, threshold=2))) == [1, 2, 3]


@pytest.mark.parametrize("threshold", [0, 5, -1])
def test_search_params_rejects_threshold_outside_1_to_4(threshold):
    with pytest.raises(ValueError):
        SearchParams(allowed_skill_ids=[0], threshold=threshold)


def test_search_with_no_skill_selected_returns_all_matching_other_filters(conn):
    # スキル未選択の場合は、スキル条件なしで他の条件のみで検索する
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    import_block(conn, build_row(zeny_count=2))  # スキルなし

    params = SearchParams(allowed_skill_ids=[])
    rows = search_results(conn, params)

    assert sorted(r.zeny_count for r in rows) == [1, 2]


def test_search_with_no_skill_selected_still_applies_other_filters(conn):
    import_block(conn, build_row(zeny_count=1, total_cost=100))
    import_block(conn, build_row(zeny_count=2, total_cost=900))

    params = SearchParams(allowed_skill_ids=[], min_total_cost=500)
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [2]


def test_search_default_sort_is_craft_order(conn):
    for i in range(1, 4):
        import_block(conn, build_row(zeny_count=i, skills=[("攻撃", 2)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2)
    rows = search_results(conn, params)

    # 既定の並びは練成順（新しいバッチから、バッチ内は練成回数昇順）
    assert [r.zeny_count for r in rows] == [3, 2, 1]


def test_search_respects_limit(conn):
    text = "\n".join(build_row(zeny_count=i, skills=[("攻撃", 2)]) for i in range(10))
    import_block(conn, text)
    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, limit=3)

    rows = search_results(conn, params)

    assert len(rows) == 3


def test_search_respects_offset_for_pagination(conn):
    text = "\n".join(build_row(zeny_count=i, skills=[("攻撃", 2)]) for i in range(1, 11))
    import_block(conn, text)

    # craft_order（既定）は1バッチ内でzeny_count昇順になるため、ページングの確認に使う
    page1 = search_results(
        conn, SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, limit=4, offset=0)
    )
    page2 = search_results(
        conn, SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, limit=4, offset=4)
    )

    assert [r.zeny_count for r in page1] == [1, 2, 3, 4]
    assert [r.zeny_count for r in page2] == [5, 6, 7, 8]


def test_search_filters_by_batch_id(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    summary2 = import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 2)]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, batch_id=summary2.batch_id)
    rows = search_results(conn, params)

    assert [r.batch_id for r in rows] == [summary2.batch_id]
    assert summary1.batch_id != summary2.batch_id


def test_search_filters_by_min_total_cost(conn):
    text = "\n".join(
        [
            build_row(zeny_count=1, total_cost=100, skills=[("攻撃", 2)]),
            build_row(zeny_count=2, total_cost=900, skills=[("攻撃", 2)]),
        ]
    )
    import_block(conn, text)

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, min_total_cost=500)
    rows = search_results(conn, params)

    assert [r.total_cost for r in rows] == [900]


def test_search_filters_by_date_range(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    conn.execute(
        "UPDATE results SET imported_at = ? WHERE batch_id = ?",
        ("2026-01-01T00:00:00", summary1.batch_id),
    )

    summary2 = import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 2)]))
    conn.execute(
        "UPDATE results SET imported_at = ? WHERE batch_id = ?",
        ("2026-06-01T00:00:00", summary2.batch_id),
    )
    conn.commit()

    params = SearchParams(
        allowed_skill_ids=_allowed_ids(conn), threshold=2, date_from="2026-03-01T00:00:00"
    )
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [2]


def test_search_filters_by_label(conn):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]), label="ギルパレ脚")
    import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 2)]), label="クシャ胴")
    import_block(conn, build_row(zeny_count=3, skills=[("攻撃", 2)]))  # ラベルなし

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, label="ギルパレ脚")
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [1]
    assert rows[0].label == "ギルパレ脚"


def test_search_matches_reference_logic_on_random_data(conn):
    rng = random.Random(1)
    skill_pool = ["攻撃", "見切り", "弱点特効", "業物", "超会心", "痛撃", "回避性能", "納刀術"]
    allowed_names = skill_pool[:3]
    threshold = 2

    lines = []
    for i in range(300):
        skill_count = rng.choice([0, 1, 1, 2, 2, 3])
        names = rng.sample(skill_pool, k=skill_count)
        skills = [(name, rng.choice([1, 2, 3])) for name in names]
        lines.append(build_row(zeny_count=1, skills=skills))
    import_block(conn, "\n".join(lines))

    registry = SkillRegistry(conn)
    allowed_ids = set(registry.get_ids(allowed_names))
    params = SearchParams(allowed_skill_ids=list(allowed_ids), threshold=threshold, limit=10_000)
    matched_ids = {r.id for r in search_results(conn, params)}

    skill_rows = conn.execute("SELECT result_id, skill_id, value FROM result_skills").fetchall()
    matched_sum_by_result: dict[int, int] = {}
    for result_id, skill_id, value in skill_rows:
        if skill_id in allowed_ids:
            matched_sum_by_result[result_id] = matched_sum_by_result.get(result_id, 0) + value
    expected_ids = {rid for rid, total in matched_sum_by_result.items() if total >= threshold}

    assert matched_ids == expected_ids
    assert len(expected_ids) > 0  # テストが無意味にならないよう最低限ヒットがあることを確認


def test_fetch_skill_breakdown_groups_by_result_id(conn):
    text = "\n".join(
        [
            build_row(zeny_count=1, skills=[("攻撃", 1), ("見切り", 1)]),
            build_row(zeny_count=2, skills=[("攻撃", 2)]),
            build_row(zeny_count=3),
        ]
    )
    import_block(conn, text)
    rows = conn.execute("SELECT id FROM results ORDER BY id").fetchall()
    result_ids = [r[0] for r in rows]

    breakdown = fetch_skill_breakdown(conn, result_ids)

    assert breakdown[result_ids[0]] == [("攻撃", 1), ("見切り", 1)]
    assert breakdown[result_ids[1]] == [("攻撃", 2)]
    assert result_ids[2] not in breakdown  # スキルなしの行は内訳に含まれない


def test_fetch_skill_breakdown_empty_list_returns_empty_dict(conn):
    assert fetch_skill_breakdown(conn, []) == {}


def test_fetch_distinct_labels_returns_sorted_unique_labels(conn):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]), label="クシャ胴")
    import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 2)]), label="ギルパレ脚")
    import_block(conn, build_row(zeny_count=3, skills=[("攻撃", 2)]), label="クシャ胴")
    import_block(conn, build_row(zeny_count=4, skills=[("攻撃", 2)]))  # ラベルなしは除外される

    assert fetch_distinct_labels(conn) == ["ギルパレ脚", "クシャ胴"]


def test_search_params_rejects_unknown_sort():
    with pytest.raises(ValueError):
        SearchParams(allowed_skill_ids=[0], sort="unknown")


def test_search_sorts_by_total_cost_descending(conn):
    text = "\n".join(
        [
            build_row(zeny_count=1, total_cost=100, skills=[("攻撃", 2)]),
            build_row(zeny_count=2, total_cost=900, skills=[("攻撃", 2)]),
            build_row(zeny_count=3, total_cost=500, skills=[("攻撃", 2)]),
        ]
    )
    import_block(conn, text)

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, sort="total_cost_desc")
    rows = search_results(conn, params)

    assert [r.total_cost for r in rows] == [900, 500, 100]


def test_search_craft_order_sorts_by_zeny_count_ascending_within_a_batch(conn):
    text = "\n".join(
        [
            build_row(zeny_count=30, skills=[("攻撃", 2)]),
            build_row(zeny_count=10, skills=[("攻撃", 2)]),
            build_row(zeny_count=20, skills=[("攻撃", 2)]),
        ]
    )
    import_block(conn, text)

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, sort="craft_order")
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [10, 20, 30]


def test_search_craft_order_lists_newest_batch_first(conn):
    # バッチA(古い)→B→C(新しい)の順で取り込んだ場合、
    # 練成順ではC→B→Aの順に並び、各バッチ内は練成回数の昇順になる
    import_block(conn, "\n".join(build_row(zeny_count=i, skills=[("攻撃", 2)]) for i in [2, 1]))
    import_block(conn, "\n".join(build_row(zeny_count=i, skills=[("攻撃", 2)]) for i in [2, 1]))
    import_block(conn, "\n".join(build_row(zeny_count=i, skills=[("攻撃", 2)]) for i in [2, 1]))

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), threshold=2, sort="craft_order", limit=6)
    rows = search_results(conn, params)

    assert [(r.batch_id, r.zeny_count) for r in rows] == [
        (3, 1),
        (3, 2),
        (2, 1),
        (2, 2),
        (1, 1),
        (1, 2),
    ]
