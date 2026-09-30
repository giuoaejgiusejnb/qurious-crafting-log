from app.core.history import fetch_batch_errors
from app.core.importer import import_block
from app.db.connection import get_connection
from app.ocr.spec import SpecChecker
from tests.helpers import build_row

MUSCLE = {"攻撃": 2, "火事場力": 3}
KUSHA = {"鋼殻の恩恵": 2, "攻撃": 2, "業物": 2, "弾丸節約": 2}


def _values(defense="+4", slot="+0", resists=("-", "-", "-", "-", "-"), skills=()):
    v = {"defense": defense, "slot_add": slot}
    v.update(zip(["fire", "water", "thunder", "ice", "dragon"], resists))
    for i in range(1, 4):
        name, lv = skills[i - 1] if i <= len(skills) else ("", "")
        v[f"skill{i}"], v[f"lv{i}"] = name, lv
    return v


def test_feasible_results_are_not_violations():
    checker = SpecChecker(5, MUSCLE)
    assert checker.violation(_values(skills=[("奮闘", "+1")])) is None
    # 攻撃 -1（コスト -10）で空いたコストで、見切り +1（15）が付く
    assert checker.violation(_values(defense="-", skills=[("見切り", "+1"), ("攻撃", "-1")])) is None


def test_defense_value_is_not_used():
    """防御力の値は判定に使わない（テーブル 6 の防御力の項目が実際と合わないため）。"""
    checker = SpecChecker(6)
    assert checker.violation(_values(defense="+37", skills=[("防御", "+1")])) is None


def test_too_many_draws():
    checker = SpecChecker(5, MUSCLE)
    v = _values(slot="+1", skills=[("奮闘", "+2"), ("激昂", "+2"), ("耳栓", "+2")])
    assert "6 回を超える" in checker.violation(v)


def test_negative_defense_needs_a_defense_draw():
    """防御力がマイナスなら防御力の抽選が 1 回以上あるので、スキルで 6 回使い切ることはできない。"""
    checker = SpecChecker(5, MUSCLE)
    skills = [("ひるみ軽減", "+2"), ("防御", "+2"), ("攻撃", "-2")]   # 6 回・コスト 6 + 6 - 20 = -8
    assert checker.violation(_values(defense="+2", skills=skills)) is None
    assert "6 回を超える" in checker.violation(_values(defense="-6", skills=skills))


def test_cost_shortage():
    checker = SpecChecker(5, MUSCLE)
    assert "コストが足りない" in checker.violation(_values(slot="+3", skills=[("見切り", "+1")]))


def test_new_skill_kind_limit():
    """元から持つスキルを含めて 5 種類まで。クシャ胴は元から 4 種類なので、それ以外のプラスは 1 種類まで。"""
    checker = SpecChecker(6, KUSHA)
    assert checker.violation(_values(skills=[("ひるみ軽減", "+1")])) is None
    assert "上限の 1 種類" in checker.violation(_values(skills=[("ひるみ軽減", "+1"), ("防御", "+1")]))
    # 元から持つスキルのプラスは種類を増やさない
    assert checker.violation(_values(defense="-", skills=[("ひるみ軽減", "+1"), ("攻撃", "-1")])) is None
    # 元から持つスキルが分からなければ種類の上限は調べない
    assert SpecChecker(6).violation(_values(skills=[("ひるみ軽減", "+1"), ("防御", "+1")])) is None


def test_unreadable_values_are_skipped():
    checker = SpecChecker(5, MUSCLE)
    assert checker.violation(_values(slot="?slot#1", skills=[("見切り", "+1")])) is None
    assert checker.violation(_values(skills=[("回復速度?", "+1")])) is None


def test_spec_issues_are_saved_as_batch_errors(tmp_path):
    conn = get_connection(tmp_path / "test.db")
    try:
        summary = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]), source="8bit",
                               spec_issues=["1 回目（a.jpg）: コストが足りない（基礎コスト 12）"])
        errors = fetch_batch_errors(conn, summary.batch_id)
        assert errors.spec == ["1 回目（a.jpg）: コストが足りない（基礎コスト 12）"]
        assert errors.total == 1 and summary.error_count == 1
    finally:
        conn.close()
