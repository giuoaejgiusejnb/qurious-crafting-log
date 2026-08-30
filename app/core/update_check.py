"""GitHub Releasesを使った、起動時の更新チェック。

リポジトリはpublicのため、認証（トークン）なしでReleases APIを呼べる。
GitHubの未認証アクセスには1時間あたり60回のレート制限があるが、
起動のたびに1回呼ぶだけなので通常の使用では問題にならない。
"""

import json
import sqlite3
import urllib.error
import urllib.request

from app.core.settings import get_setting, set_setting

GITHUB_OWNER = "giuoaejgiusejnb"
GITHUB_REPO = "qurious-crafting-log"

# 起動時の更新チェックを行うかどうかの設定キー（app_settingsテーブルに保存）。
# 未設定（初回起動時など）は「有効」として扱う。
UPDATE_CHECK_ENABLED_KEY = "update_check_enabled"

_LATEST_RELEASE_API_URL = (
    f"https://api.github.com/repos/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
)
RELEASE_PAGE_URL = f"https://github.com/{GITHUB_OWNER}/{GITHUB_REPO}/releases/latest"
_REQUEST_TIMEOUT_SECONDS = 5


def fetch_latest_release_tag() -> str | None:
    """GitHub上の最新リリースのタグ名を取得する。

    オフライン・GitHub側の障害・レート制限などで取得できない場合はNoneを返す
    （更新チェックはあくまで補助的な機能のため、失敗時は何も表示せず静かに諦める）。
    """
    request = urllib.request.Request(
        _LATEST_RELEASE_API_URL,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"{GITHUB_REPO}-update-check",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=_REQUEST_TIMEOUT_SECONDS) as response:
            data = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError):
        return None

    tag_name = data.get("tag_name")
    return tag_name if isinstance(tag_name, str) and tag_name else None


def is_update_available(current_version: str, latest_tag: str | None) -> bool:
    """現在のバージョンと最新タグを比較する。

    タグ名（例: "v1.01"）は厳密なセマンティックバージョニングに従っていないため、
    大小比較はせず「現在のバージョンと違うタグが最新である」ことだけを判定する。
    """
    return latest_tag is not None and latest_tag != current_version


def is_update_check_enabled(conn: sqlite3.Connection) -> bool:
    """起動時の更新チェックが有効かどうか。未設定（初回起動など）はTrue扱い。"""
    return get_setting(conn, UPDATE_CHECK_ENABLED_KEY) != "0"


def set_update_check_enabled(conn: sqlite3.Connection, enabled: bool) -> None:
    set_setting(conn, UPDATE_CHECK_ENABLED_KEY, "1" if enabled else "0")
