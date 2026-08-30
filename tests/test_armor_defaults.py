import pytest

from app.core.armor_defaults import (
    ArmorSearchDefaults,
    get_armor_defaults,
    list_armors_using_skill_set,
    reset_armor_defaults,
    set_armor_defaults,
)
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_get_armor_defaults_returns_default_when_unset(conn):
    defaults = get_armor_defaults(conn, "ギルパレ脚")
    assert defaults == ArmorSearchDefaults()


def test_set_and_get_armor_defaults_roundtrip(conn):
    saved = ArmorSearchDefaults(
        skill_set_name="攻撃セット",
        threshold=3,
        min_total_cost=6,
        max_total_cost=30,
        min_resistance=-3,
        max_resistance=3,
        has_deficiency=0,
        sort="total_cost_desc",
    )
    set_armor_defaults(conn, "クシャ胴", saved)

    assert get_armor_defaults(conn, "クシャ胴") == saved
    # 他の防具には影響しない
    assert get_armor_defaults(conn, "ギルパレ脚") == ArmorSearchDefaults()


def test_set_armor_defaults_for_multiple_armors_independently(conn):
    set_armor_defaults(conn, "A", ArmorSearchDefaults(threshold=4))
    set_armor_defaults(conn, "B", ArmorSearchDefaults(threshold=1))

    assert get_armor_defaults(conn, "A").threshold == 4
    assert get_armor_defaults(conn, "B").threshold == 1


def test_reset_armor_defaults_restores_default(conn):
    set_armor_defaults(conn, "クシャ胴", ArmorSearchDefaults(threshold=4))
    reset_armor_defaults(conn, "クシャ胴")

    assert get_armor_defaults(conn, "クシャ胴") == ArmorSearchDefaults()


def test_reset_armor_defaults_is_noop_when_unset(conn):
    reset_armor_defaults(conn, "未設定の防具")  # 例外にならない
    assert get_armor_defaults(conn, "未設定の防具") == ArmorSearchDefaults()


def test_list_armors_using_skill_set_finds_matching_armors(conn):
    set_armor_defaults(conn, "A", ArmorSearchDefaults(skill_set_name="攻撃セット"))
    set_armor_defaults(conn, "B", ArmorSearchDefaults(skill_set_name="攻撃セット"))
    set_armor_defaults(conn, "C", ArmorSearchDefaults(skill_set_name="回復セット"))
    set_armor_defaults(conn, "D", ArmorSearchDefaults(skill_set_name=None))

    assert list_armors_using_skill_set(conn, "攻撃セット") == ["A", "B"]
    assert list_armors_using_skill_set(conn, "回復セット") == ["C"]
    assert list_armors_using_skill_set(conn, "存在しない集合") == []
