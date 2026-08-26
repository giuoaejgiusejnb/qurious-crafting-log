import random

import pytest

from app.core.importer import import_block
from app.core.search import SearchParams, fetch_distinct_labels, fetch_skill_breakdown, search_results
from app.core.skill_mask import matches_allowed_set
from app.core.skill_registry import SkillRegistry
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


SAMPLE_TEXT = "\n".join(
    [
        "1,1,1,1,0,0,攻撃+1,見切り+1",  # 対象: 許可集合内、合計2
        "2,1,1,1,0,0,攻撃+2",  # 対象: 単一スキルで合計2
        "3,1,1,1,0,0,攻撃+1",  # 対象外: 合計1
        "4,1,1,1,0,0,攻撃+1,爆破+1",  # 対象外: 許可集合外のスキルを含む
        "5,1,1,1,0,0",  # 対象外: スキルなし
    ]
)


def _allowed_ids(conn):
    registry = SkillRegistry(conn)
    return registry.get_ids(["攻撃", "見切り", "弱点特効"])


def test_search_matches_examples_from_requirements(conn):
    import_block(conn, SAMPLE_TEXT)
    params = SearchParams(allowed_skill_ids=_allowed_ids(conn))

    rows = search_results(conn, params)

    assert sorted(r.zeny_count for r in rows) == [1, 2]


def test_search_respects_limit(conn):
    text = "\n".join(f"{i},1,1,1,0,0,攻撃+2" for i in range(10))
    import_block(conn, text)
    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), limit=3)

    rows = search_results(conn, params)

    assert len(rows) == 3


def test_search_filters_by_batch_id(conn):
    summary1 = import_block(conn, "1,1,1,1,0,0,攻撃+2")
    summary2 = import_block(conn, "2,1,1,1,0,0,攻撃+2")

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), batch_id=summary2.batch_id)
    rows = search_results(conn, params)

    assert [r.batch_id for r in rows] == [summary2.batch_id]
    assert summary1.batch_id != summary2.batch_id


def test_search_filters_by_min_total_cost(conn):
    text = "\n".join(
        [
            "1,1,1,100,0,0,攻撃+2",
            "2,1,1,900,0,0,攻撃+2",
        ]
    )
    import_block(conn, text)

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), min_total_cost=500)
    rows = search_results(conn, params)

    assert [r.total_cost for r in rows] == [900]


def test_search_filters_by_date_range(conn):
    summary1 = import_block(conn, "1,1,1,1,0,0,攻撃+2")
    conn.execute(
        "UPDATE results SET imported_at = ? WHERE batch_id = ?",
        ("2026-01-01T00:00:00", summary1.batch_id),
    )

    summary2 = import_block(conn, "2,1,1,1,0,0,攻撃+2")
    conn.execute(
        "UPDATE results SET imported_at = ? WHERE batch_id = ?",
        ("2026-06-01T00:00:00", summary2.batch_id),
    )
    conn.commit()

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), date_from="2026-03-01T00:00:00")
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [2]


def test_search_matches_reference_logic_on_random_data(conn):
    rng = random.Random(1)
    skill_pool = ["攻撃", "見切り", "弱点特効", "業物", "超会心", "痛撃", "回避性能", "納刀術"]
    allowed_names = skill_pool[:3]

    lines = []
    for i in range(300):
        skill_count = rng.choice([0, 1, 1, 2, 2, 3])
        names = rng.sample(skill_pool, k=skill_count)
        skill_tokens = [f"{name}+{rng.choice([1, 2, 3])}" for name in names]
        line = ",".join(["1", "1", "1", "1", "0", "0", *skill_tokens])
        lines.append(line)
    import_block(conn, "\n".join(lines))

    registry = SkillRegistry(conn)
    allowed_ids = registry.get_ids(allowed_names)
    params = SearchParams(allowed_skill_ids=allowed_ids, limit=10_000)
    rows = search_results(conn, params)
    matched_ids = {r.id for r in rows}

    all_rows = conn.execute(
        "SELECT id, skill_mask_lo, skill_mask_hi, skill_sum FROM results"
    ).fetchall()
    from app.core.skill_mask import compute_mask

    allowed_lo, allowed_hi = compute_mask(allowed_ids)
    expected_ids = {
        rid
        for rid, lo, hi, s in all_rows
        if matches_allowed_set(lo, hi, s, allowed_lo, allowed_hi)
    }

    assert matched_ids == expected_ids
    assert len(expected_ids) > 0  # テストが無意味にならないよう最低限ヒットがあることを確認


def test_fetch_skill_breakdown_groups_by_result_id(conn):
    import_block(conn, SAMPLE_TEXT)
    rows = conn.execute("SELECT id FROM results ORDER BY id").fetchall()
    result_ids = [r[0] for r in rows]

    breakdown = fetch_skill_breakdown(conn, result_ids)

    assert breakdown[result_ids[0]] == [("攻撃", 1), ("見切り", 1)]
    assert breakdown[result_ids[1]] == [("攻撃", 2)]
    assert result_ids[4] not in breakdown  # スキルなしの行は内訳に含まれない


def test_fetch_skill_breakdown_empty_list_returns_empty_dict(conn):
    assert fetch_skill_breakdown(conn, []) == {}


def test_search_filters_by_label(conn):
    import_block(conn, "1,1,1,1,0,0,攻撃+2", label="ギルパレ脚")
    import_block(conn, "2,1,1,1,0,0,攻撃+2", label="クシャ胴")
    import_block(conn, "3,1,1,1,0,0,攻撃+2")  # ラベルなし

    params = SearchParams(allowed_skill_ids=_allowed_ids(conn), label="ギルパレ脚")
    rows = search_results(conn, params)

    assert [r.zeny_count for r in rows] == [1]
    assert rows[0].label == "ギルパレ脚"


def test_fetch_distinct_labels_returns_sorted_unique_labels(conn):
    import_block(conn, "1,1,1,1,0,0,攻撃+2", label="クシャ胴")
    import_block(conn, "2,1,1,1,0,0,攻撃+2", label="ギルパレ脚")
    import_block(conn, "3,1,1,1,0,0,攻撃+2", label="クシャ胴")
    import_block(conn, "4,1,1,1,0,0,攻撃+2")  # ラベルなしは除外される

    assert fetch_distinct_labels(conn) == ["ギルパレ脚", "クシャ胴"]
