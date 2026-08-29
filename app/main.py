import os
import shutil
from pathlib import Path

import flet as ft

from app.ui.collection_view import build_collection_view
from app.ui.history_view import build_history_view
from app.ui.import_view import build_import_view
from app.ui.search_view import build_search_view

APP_DATA_DIR_NAME = "QuriousCraftingLog"
DB_FILE_NAME = "qurious_crafting_log.db"

# 以前はプロジェクト直下のdata/フォルダを使っていたが、
# OneDrive等でデスクトップ配下が自動同期される環境（特にexe配布先）だと
# 書き込み中のSQLiteファイルが同期と競合して壊れるおそれがあるため、
# 同期対象外である%LOCALAPPDATA%配下へ変更した。
_LEGACY_DB_PATH = Path(__file__).resolve().parent.parent / "data" / DB_FILE_NAME


def _default_data_dir() -> Path:
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / APP_DATA_DIR_NAME
    return Path.home() / f".{APP_DATA_DIR_NAME.lower()}"  # Windows以外向けフォールバック


DB_PATH = _default_data_dir() / DB_FILE_NAME


def _migrate_legacy_db_if_needed() -> None:
    """旧保存先（プロジェクト直下data/）にDBがあり、新保存先にまだ無い場合、一度だけ引き継ぐ。"""
    if DB_PATH.exists() or not _LEGACY_DB_PATH.exists():
        return
    for suffix in ("", "-wal", "-shm"):
        legacy_file = _LEGACY_DB_PATH.with_name(_LEGACY_DB_PATH.name + suffix)
        if legacy_file.exists():
            shutil.copy2(legacy_file, DB_PATH.with_name(DB_PATH.name + suffix))


def main(page: ft.Page) -> None:
    page.title = "モンハン錬成結果 記録・検索"
    # OS側がダークモードだと配色が見づらくなるため、常にライトモードで固定表示する
    page.theme_mode = ft.ThemeMode.LIGHT
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _migrate_legacy_db_if_needed()

    # スクロールバーの定義（デフォルトだと薄くて見えにくいため）
    page.theme = ft.Theme(
        scrollbar_theme=ft.ScrollbarTheme(
            track_color={  # バーが通る道の部分の色
                ft.ControlState.HOVERED: ft.Colors.BLUE_GREY_50,  # マウスを乗せた時の色
                ft.ControlState.DEFAULT: ft.Colors.TRANSPARENT,  # 通常時の色
            },
            thumb_color={  # 動くバーの部分の色
                ft.ControlState.HOVERED: ft.Colors.BLUE_GREY_400,
                ft.ControlState.DEFAULT: ft.Colors.BLUE_GREY_200,
            },
            thickness=10,  # バーの太さ（デフォルトは短い）
            radius=5,  # 角の丸み
            main_axis_margin=5,
            cross_axis_margin=5,
            interactive=True,  # ドラッグ可能にする
        )
    )

    # 検索・履歴・回収タブを先に構築し、それぞれの「一覧を最新化する」関数を取得しておく。
    # 取込タブ側は取込成功時にこれらを呼び出すことで、再起動なしに反映されるようにする。
    # select_search_batchは検索タブに新設した「指定バッチを対象に検索する」関数で、
    # 取込タブ・履歴タブからの連携用に今後配線する（現時点では未使用）。
    search_view, refresh_search_filters, select_search_batch = build_search_view(page, DB_PATH)
    history_view, refresh_history_batches = build_history_view(page, DB_PATH)
    collection_view, refresh_collection_batches = build_collection_view(page, DB_PATH)

    def on_imported() -> None:
        refresh_search_filters()
        refresh_history_batches()
        refresh_collection_batches()

    import_view = build_import_view(page, DB_PATH, on_imported=on_imported)

    page.add(
        ft.Tabs(
            length=4,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label="取込"),
                            ft.Tab(label="検索"),
                            ft.Tab(label="履歴"),
                            ft.Tab(label="回収"),
                        ]
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            import_view,
                            search_view,
                            history_view,
                            collection_view,
                        ],
                    ),
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
