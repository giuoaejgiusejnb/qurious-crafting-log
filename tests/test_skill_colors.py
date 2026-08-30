import pytest

from app.core.skill_colors import (
    DEFAULT_NEGATIVE_COLOR,
    DEFAULT_POSITIVE_COLOR,
    get_negative_skill_color,
    get_positive_skill_color,
    resolve_color,
    set_negative_skill_color,
    set_positive_skill_color,
)
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_positive_color_defaults(conn):
    assert get_positive_skill_color(conn) == DEFAULT_POSITIVE_COLOR


def test_negative_color_defaults(conn):
    assert get_negative_skill_color(conn) == DEFAULT_NEGATIVE_COLOR


def test_set_and_get_positive_color_roundtrip(conn):
    set_positive_skill_color(conn, "blue")
    assert get_positive_skill_color(conn) == "blue"


def test_set_and_get_negative_color_roundtrip(conn):
    set_negative_skill_color(conn, "purple")
    assert get_negative_skill_color(conn) == "purple"


def test_get_positive_color_falls_back_to_default_for_invalid_stored_value(conn):
    # 想定していない値がDBに入っていても（手動編集や仕様変更などで）落ちずに既定値を返す
    from app.core.settings import set_setting

    set_setting(conn, "skill_color_positive", "not_a_real_color")
    assert get_positive_skill_color(conn) == DEFAULT_POSITIVE_COLOR


def test_resolve_color_default_is_none():
    assert resolve_color("default") is None


def test_resolve_color_passes_through_other_values():
    assert resolve_color("red") == "red"
    assert resolve_color("blue") == "blue"
