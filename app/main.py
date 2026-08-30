import os
import shutil
from pathlib import Path

import flet as ft

from app.core.update_check import RELEASE_PAGE_URL, fetch_latest_release_tag, is_update_available
from app.ui.collection_view import build_collection_view
from app.ui.history_view import build_history_view
from app.ui.import_view import build_import_view
from app.ui.search_view import build_search_view
from app.ui.settings_view import build_settings_view
from app.version import APP_VERSION

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

    # 検索・回収タブを先に構築し、それぞれの「一覧を最新化する」関数を取得しておく。
    # 取込タブ側は取込成功時にこれらを呼び出すことで、再起動なしに反映されるようにする。
    search_view, refresh_search_filters, select_search_batch = build_search_view(page, DB_PATH)
    collection_view, refresh_collection_batches = build_collection_view(page, DB_PATH)

    SEARCH_TAB_INDEX = 1

    def go_to_search_with_batch(batch_id: int) -> None:
        """取込タブ・履歴タブから呼ばれ、検索タブへ切り替えて指定バッチを対象に検索する。"""
        tabs_control.selected_index = SEARCH_TAB_INDEX
        select_search_batch(batch_id)

    def on_batch_deleted() -> None:
        """履歴タブでのバッチ削除時に外部から呼ばれ、他タブのバッチ一覧を最新化する。"""
        refresh_search_filters()
        refresh_collection_batches()

    history_view, refresh_history_batches = build_history_view(
        page, DB_PATH, on_batch_deleted=on_batch_deleted, on_batch_selected=go_to_search_with_batch
    )

    def on_imported(batch_id: int) -> None:
        refresh_search_filters()
        refresh_history_batches()
        refresh_collection_batches()

    import_view = build_import_view(
        page, DB_PATH, on_imported=on_imported, on_show_results=go_to_search_with_batch
    )

    settings_view = build_settings_view(page, DB_PATH)

    tabs_control = ft.Tabs(
        length=5,
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
                        ft.Tab(label="設定"),
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        import_view,
                        search_view,
                        history_view,
                        collection_view,
                        settings_view,
                    ],
                ),
            ],
        ),
    )
    page.add(tabs_control)

    # --- キーボードのPageUp/PageDownで、表示中のタブをスクロールする ---
    # 矢印キー（上下）はドロップダウンの選択肢移動などコントロール側でも使われており、
    # 開いている間はページスクロールを確実に防げないため見送った
    # （PageUp/PageDownはどのコントロールも内部で使っていないため競合しない）。
    _PAGE_KEY_STEP = 400  # PageUp/PageDownキー1回あたりのスクロール量(px)

    _tab_views = [import_view, search_view, history_view, collection_view, settings_view]

    async def scroll_active_tab(delta: float) -> None:
        active_view = _tab_views[tabs_control.selected_index]
        await active_view.scroll_to(delta=delta, duration=0)

    def on_keyboard_event(e: ft.KeyboardEvent) -> None:
        if e.key == "Page Down":
            page.run_task(scroll_active_tab, _PAGE_KEY_STEP)
        elif e.key == "Page Up":
            page.run_task(scroll_active_tab, -_PAGE_KEY_STEP)

    page.on_keyboard_event = on_keyboard_event

    # --- 起動時の更新チェック ---
    # GitHub Releasesの最新タグを取得し、現在のバージョン（app/version.py）と
    # 異なれば「ダウンロードページを開くか」を確認する。オフライン等で取得に
    # 失敗した場合は何も表示せず静かに諦める（更新チェックはあくまで補助機能）。
    def show_update_dialog(latest_tag: str) -> None:
        async def on_yes(e: ft.Event[ft.Button]) -> None:
            page.pop_dialog()
            await ft.UrlLauncher().launch_url(RELEASE_PAGE_URL)

        def on_no(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("新しいバージョンがあります"),
            content=ft.Text(
                f"現在のバージョン: {APP_VERSION}\n最新バージョン: {latest_tag}\n\n"
                "ダウンロードページを開きますか？"
            ),
            actions=[
                ft.TextButton(content="いいえ", on_click=on_no),
                ft.Button(content="はい", on_click=on_yes),
            ],
        )
        page.show_dialog(dialog)
        page.update()

    def check_for_update() -> None:
        latest_tag = fetch_latest_release_tag()
        if latest_tag is not None and is_update_available(APP_VERSION, latest_tag):
            show_update_dialog(latest_tag)

    page.run_thread(check_for_update)


if __name__ == "__main__":
    ft.run(main)
