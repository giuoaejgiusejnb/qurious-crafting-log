"""検索結果・回収一覧のスキル表示色（プラス値/マイナス値）の設定。

キーはft.Text(color=...)にそのまま渡せる値を使う（Fletは"red"のような
色名文字列をそのまま受け付けるため、UI側で変換する必要がない）。
"default"だけは特別扱いで、色を指定しない（テーマの既定文字色のまま）ことを表す。
"""

import sqlite3

from app.core.settings import get_setting, set_setting

POSITIVE_COLOR_KEY = "skill_color_positive"
NEGATIVE_COLOR_KEY = "skill_color_negative"

DEFAULT_POSITIVE_COLOR = "default"  # 既定色（テーマの文字色のまま）
DEFAULT_NEGATIVE_COLOR = "red"  # 従来からのマイナススキルの色

# 設定タブの色選択肢（キー, 表示名）。
COLOR_CHOICES: list[tuple[str, str]] = [
    ("default", "既定色"),
    ("red", "赤"),
    ("orange", "オレンジ"),
    ("amber", "黄色"),
    ("green", "緑"),
    ("blue", "青"),
    ("purple", "紫"),
    ("pink", "ピンク"),
    ("brown", "茶色"),
    ("grey", "グレー"),
    ("black", "黒"),
]
COLOR_KEYS = {key for key, _label in COLOR_CHOICES}


def get_positive_skill_color(conn: sqlite3.Connection) -> str:
    value = get_setting(conn, POSITIVE_COLOR_KEY)
    return value if value in COLOR_KEYS else DEFAULT_POSITIVE_COLOR


def set_positive_skill_color(conn: sqlite3.Connection, color_key: str) -> None:
    set_setting(conn, POSITIVE_COLOR_KEY, color_key)


def get_negative_skill_color(conn: sqlite3.Connection) -> str:
    value = get_setting(conn, NEGATIVE_COLOR_KEY)
    return value if value in COLOR_KEYS else DEFAULT_NEGATIVE_COLOR


def set_negative_skill_color(conn: sqlite3.Connection, color_key: str) -> None:
    set_setting(conn, NEGATIVE_COLOR_KEY, color_key)


def resolve_color(color_key: str) -> str | None:
    """設定値からft.Text(color=...)に渡す値を返す。"default"はNone（テーマの既定色）。"""
    return None if color_key == "default" else color_key
