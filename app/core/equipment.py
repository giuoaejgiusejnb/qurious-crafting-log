import sqlite3

from app.core.settings import get_json_setting

DEFAULT_EQUIPMENT_OPTIONS = ["ギルパレ脚", "クシャ胴", "マッスル腕"]
CUSTOM_OPTIONS_KEY = "import_label_custom_options"

# 練成画像から取込（8bit）で使う、防具ごとの初期値（取込タブで変更すると防具ごとに記憶する）
#   base_slot   : 初期スロット
#   zenny_step  : 1回の練成で減るゼニー
#   minus_skills: 防具が元から持つスキルと元のレベル（「スキル名:Lv」をカンマ区切り）
#   table       : 傀異錬成の抽選テーブル（"5" / "6"。"none" は不明で、仕様のチェックを行わない。
#                 "" は未設定で、初期値があればそれを使う）
TABLE_NONE = "none"
DEFAULT_OCR_PARAMS: dict[str, dict[str, str]] = {
    "ギルパレ脚": {"base_slot": "3", "zenny_step": "4000", "minus_skills": "火事場力:2,災禍転福:2", "table": "6"},
    "クシャ胴": {
        "base_slot": "6",
        "zenny_step": "6000",
        "minus_skills": "鋼殻の恩恵:2,攻撃:2,業物:2,弾丸節約:2",
        "table": "6",
    },
    "マッスル腕": {"base_slot": "6", "zenny_step": "4000", "minus_skills": "攻撃:2,火事場力:3", "table": "5"},
}
OCR_PARAM_FALLBACK = {"base_slot": "", "zenny_step": "4000", "minus_skills": "", "table": ""}


def resolve_ocr_params(saved: dict[str, dict[str, str]], label: str) -> dict[str, str]:
    """防具の取込設定を、保存済みの値 > 防具ごとの初期値 > 空欄 の順で埋めて返す。

    保存済みの値に無い項目・空欄の項目は、初期値で補う（初期値を用意する前に、空欄のまま
    保存された設定があるため）。抽選テーブルの「なし」は "none" として保存するので、空欄とは区別される。
    """
    filled = {key: value for key, value in saved.get(label, {}).items() if value}
    return {**OCR_PARAM_FALLBACK, **DEFAULT_OCR_PARAMS.get(label, {}), **filled}


def list_all_equipment_options(conn: sqlite3.Connection) -> list[str]:
    """取込タブで選択できる防具名（デフォルト＋ユーザー追加分）の一覧を返す。

    設定タブ（防具ごとの検索初期設定）でも、取込タブと同じ防具一覧を使うため
    ここに集約する。
    """
    custom_options = get_json_setting(conn, CUSTOM_OPTIONS_KEY, [])
    options = list(DEFAULT_EQUIPMENT_OPTIONS)
    for opt in custom_options:
        if opt not in options:
            options.append(opt)
    return options
