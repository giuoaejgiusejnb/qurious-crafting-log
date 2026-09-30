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


def test_default_ocr_params_use_known_skill_names():
    from app.core.equipment import DEFAULT_OCR_PARAMS
    from app.core.skill_master import ALL_MASTER_SKILL_NAMES
    from app.ocr.kuijin_ocr import parse_minus_skills

    for armor, params in DEFAULT_OCR_PARAMS.items():
        skills = parse_minus_skills(params["minus_skills"]) or {}
        assert set(skills) <= ALL_MASTER_SKILL_NAMES, armor
        assert params["table"] in ("5", "6")


def test_resolve_ocr_params_prefers_saved_and_fills_missing_keys():
    from app.core.equipment import resolve_ocr_params

    # テーブルの項目を追加する前に保存された値: 保存済みの値を使い、テーブルは初期値で補う
    saved = {"マッスル腕": {"base_slot": "6", "zenny_step": "4000", "minus_skills": "攻撃:2"}}
    params = resolve_ocr_params(saved, "マッスル腕")
    assert params["minus_skills"] == "攻撃:2"
    assert params["table"] == "5"
    assert resolve_ocr_params({}, "クシャ胴")["zenny_step"] == "6000"
    assert resolve_ocr_params({}, "自作の防具") == {"base_slot": "", "zenny_step": "4000", "minus_skills": "", "table": ""}


def test_resolve_ocr_params_fills_blank_saved_values():
    """初期値を用意する前に空欄のまま保存された設定は、初期値で補う。「なし」は "none" なので補わない。"""
    from app.core.equipment import TABLE_NONE, resolve_ocr_params

    saved = {"ギルパレ脚": {"base_slot": "3", "zenny_step": "4000", "minus_skills": "", "table": ""}}
    params = resolve_ocr_params(saved, "ギルパレ脚")
    assert params["minus_skills"] == "火事場力:2,災禍転福:2"
    assert params["table"] == "6"

    saved = {"ギルパレ脚": {"base_slot": "3", "zenny_step": "4000", "minus_skills": "", "table": TABLE_NONE}}
    assert resolve_ocr_params(saved, "ギルパレ脚")["table"] == TABLE_NONE
