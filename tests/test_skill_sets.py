import pytest

from app.core.skill_sets import delete_skill_set, get_skill_set, list_skill_set_names, save_skill_set
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_save_and_get_skill_set_roundtrip(conn):
    save_skill_set(conn, "対人セット", ["攻撃", "見切り", "弱点特効"])
    assert get_skill_set(conn, "対人セット") == ["攻撃", "見切り", "弱点特効"]


def test_get_skill_set_returns_none_when_missing(conn):
    assert get_skill_set(conn, "存在しない") is None


def test_save_skill_set_overwrites_existing_name(conn):
    save_skill_set(conn, "セットA", ["攻撃"])
    save_skill_set(conn, "セットA", ["見切り", "弱点特効"])
    assert get_skill_set(conn, "セットA") == ["見切り", "弱点特効"]


def test_list_skill_set_names_returns_sorted_names(conn):
    save_skill_set(conn, "ぞ", ["攻撃"])
    save_skill_set(conn, "あ", ["見切り"])
    assert list_skill_set_names(conn) == ["あ", "ぞ"]


def test_delete_skill_set_removes_entry(conn):
    save_skill_set(conn, "セットA", ["攻撃"])
    delete_skill_set(conn, "セットA")
    assert get_skill_set(conn, "セットA") is None
    assert list_skill_set_names(conn) == []


def test_delete_skill_set_ignores_missing_name(conn):
    delete_skill_set(conn, "存在しない")  # 例外にならないこと
