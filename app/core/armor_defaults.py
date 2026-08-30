import json
import sqlite3
from dataclasses import asdict, dataclass

from app.core.search import DEFAULT_SORT
from app.core.settings import get_setting, set_setting

# app_settingsに保存するキー。値は防具名 -> ArmorSearchDefaults(asdict) のJSON。
_SETTINGS_KEY = "armor_search_defaults"


@dataclass
class ArmorSearchDefaults:
    """防具ごとの検索初期設定（取込タブから検索タブへ自動遷移する際に適用する）。

    skill_set_nameは保存済みスキル集合の名前を参照する（値そのものではなく名前で
    参照するため、参照先の集合が後から編集されれば、この初期設定にも反映される）。
    参照先が削除された場合は、検索時にスキル未選択として扱う
    （app/ui/search_view.pyのselect_batch_and_search参照）。
    """

    skill_set_name: str | None = None
    threshold: int = 1  # 検索タブ自体の初期値（1）と合わせる
    min_total_cost: int = 3
    max_total_cost: int = 42
    min_resistance: int | None = None
    max_resistance: int | None = None
    has_deficiency: int | None = None
    sort: str = DEFAULT_SORT


def _load_all(conn: sqlite3.Connection) -> dict[str, dict]:
    raw = get_setting(conn, _SETTINGS_KEY)
    if raw is None:
        return {}
    return json.loads(raw)


def _save_all(conn: sqlite3.Connection, all_defaults: dict[str, dict]) -> None:
    set_setting(conn, _SETTINGS_KEY, json.dumps(all_defaults, ensure_ascii=False))


def get_armor_defaults(conn: sqlite3.Connection, armor_name: str) -> ArmorSearchDefaults:
    """指定した防具の検索初期設定を取得する。未設定なら既定値を返す。"""
    data = _load_all(conn).get(armor_name)
    if data is None:
        return ArmorSearchDefaults()
    return ArmorSearchDefaults(**data)


def set_armor_defaults(conn: sqlite3.Connection, armor_name: str, defaults: ArmorSearchDefaults) -> None:
    """指定した防具の検索初期設定を保存する。"""
    all_defaults = _load_all(conn)
    all_defaults[armor_name] = asdict(defaults)
    _save_all(conn, all_defaults)


def reset_armor_defaults(conn: sqlite3.Connection, armor_name: str) -> None:
    """指定した防具の検索初期設定を削除する（既定値に戻す）。"""
    all_defaults = _load_all(conn)
    if armor_name in all_defaults:
        del all_defaults[armor_name]
        _save_all(conn, all_defaults)


def list_armors_using_skill_set(conn: sqlite3.Connection, skill_set_name: str) -> list[str]:
    """指定したスキル集合名を検索初期設定として使っている防具名の一覧を返す。

    スキル集合の削除確認（app/ui/search_view.py）で、削除すると初期設定に
    影響する防具があることを警告するために使う。
    """
    all_defaults = _load_all(conn)
    return sorted(
        armor
        for armor, data in all_defaults.items()
        if data.get("skill_set_name") == skill_set_name
    )
