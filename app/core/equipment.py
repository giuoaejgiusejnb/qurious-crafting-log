import sqlite3

from app.core.settings import get_json_setting

DEFAULT_EQUIPMENT_OPTIONS = ["ギルパレ脚", "クシャ胴", "マッスル腕"]
CUSTOM_OPTIONS_KEY = "import_label_custom_options"


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
