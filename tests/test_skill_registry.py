import sqlite3

import pytest

from app.core.skill_registry import SkillRegistry
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    db_path = tmp_path / "test.db"
    connection = get_connection(db_path)
    yield connection
    connection.close()


def test_schema_creates_expected_tables(conn: sqlite3.Connection):
    tables = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    assert {"skills", "import_batches", "results", "result_skills"} <= tables


def test_get_or_create_id_assigns_sequential_bit_index(conn: sqlite3.Connection):
    registry = SkillRegistry(conn)
    assert registry.get_or_create_id("攻撃") == 0
    assert registry.get_or_create_id("見切り") == 1
    assert registry.get_or_create_id("攻撃") == 0  # 既存名は同じIDを返す
    assert registry.get_or_create_id("弱点特効") == 2


def test_registry_reloads_existing_skills_from_db(conn: sqlite3.Connection):
    first = SkillRegistry(conn)
    first.get_or_create_id("攻撃")
    conn.commit()

    second = SkillRegistry(conn)
    assert second.get_or_create_id("攻撃") == 0
    assert second.get_or_create_id("見切り") == 1


def test_get_ids_ignores_unknown_names(conn: sqlite3.Connection):
    registry = SkillRegistry(conn)
    registry.get_or_create_id("攻撃")
    registry.get_or_create_id("見切り")

    assert registry.get_ids(["攻撃", "未登録スキル", "見切り"]) == [0, 1]
