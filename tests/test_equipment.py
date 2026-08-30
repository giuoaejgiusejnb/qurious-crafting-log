import pytest

from app.core.equipment import CUSTOM_OPTIONS_KEY, DEFAULT_EQUIPMENT_OPTIONS, list_all_equipment_options
from app.core.settings import set_json_setting
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_list_all_equipment_options_returns_defaults_when_no_custom(conn):
    assert list_all_equipment_options(conn) == DEFAULT_EQUIPMENT_OPTIONS


def test_list_all_equipment_options_includes_custom_options(conn):
    set_json_setting(conn, CUSTOM_OPTIONS_KEY, ["自作装備A"])

    options = list_all_equipment_options(conn)

    assert options == [*DEFAULT_EQUIPMENT_OPTIONS, "自作装備A"]


def test_list_all_equipment_options_does_not_duplicate_defaults(conn):
    set_json_setting(conn, CUSTOM_OPTIONS_KEY, [DEFAULT_EQUIPMENT_OPTIONS[0], "自作装備A"])

    options = list_all_equipment_options(conn)

    assert options == [*DEFAULT_EQUIPMENT_OPTIONS, "自作装備A"]
