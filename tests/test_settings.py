import pytest

from app.core.settings import get_json_setting, get_setting, set_json_setting, set_setting
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_get_setting_returns_none_when_missing(conn):
    assert get_setting(conn, "unknown_key") is None


def test_set_and_get_setting_roundtrip(conn):
    set_setting(conn, "last_selection", "ギルパレ脚")
    assert get_setting(conn, "last_selection") == "ギルパレ脚"


def test_set_setting_overwrites_existing_value(conn):
    set_setting(conn, "last_selection", "ギルパレ脚")
    set_setting(conn, "last_selection", "クシャ胴")
    assert get_setting(conn, "last_selection") == "クシャ胴"


def test_get_json_setting_returns_default_when_missing(conn):
    assert get_json_setting(conn, "custom_options", []) == []
    assert get_json_setting(conn, "custom_options", ["a"]) == ["a"]


def test_set_and_get_json_setting_roundtrip(conn):
    set_json_setting(conn, "custom_options", ["俺の装備A", "俺の装備B"])
    assert get_json_setting(conn, "custom_options", []) == ["俺の装備A", "俺の装備B"]
