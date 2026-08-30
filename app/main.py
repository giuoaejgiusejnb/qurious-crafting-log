import os
import shutil
from pathlib import Path

import flet as ft

from app.core.armor_defaults import get_armor_defaults
from app.core.update_check import (
    RELEASE_PAGE_URL,
    fetch_latest_release_tag,
    is_update_available,
    is_update_check_enabled,
    set_update_check_enabled,
)
from app.db.connection import get_connection
from app.ui.collection_panel import build_collection_panel
from app.ui.contact_view import build_contact_view
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

    # 検索タブを先に構築し、「一覧を最新化する」関数を取得しておく。
    # 取込タブ側は取込成功時にこれを呼び出すことで、再起動なしに反映されるようにする。
    # on_collectedは検索タブで「回収」にチェックを入れたときに呼ばれ、
    # そのバッチの回収確認サイドパネルを自動的に開くのに使う。
    collection_panel, open_collection_panel, close_collection_panel = build_collection_panel(
        page, DB_PATH
    )
    search_view, refresh_search_filters, select_search_batch = build_search_view(
        page, DB_PATH, on_collected=open_collection_panel
    )

    SEARCH_TAB_INDEX = 1
    SETTINGS_TAB_INDEX = 3

    def go_to_search_with_batch(batch_id: int) -> None:
        """履歴タブから呼ばれ、検索タブへ切り替えて指定バッチを対象に検索する。

        条件は常にすべてリセットされる（防具ごとの検索初期設定は適用しない）。
        """
        tabs_control.selected_index = SEARCH_TAB_INDEX
        select_search_batch(batch_id)

    def go_to_search_after_import(batch_id: int, armor_label: str | None) -> None:
        """取込タブから呼ばれ、検索タブへ切り替えて指定バッチを対象に検索する。

        armor_labelに対応する防具ごとの検索初期設定（設定タブ）があれば適用する。
        """
        tabs_control.selected_index = SEARCH_TAB_INDEX
        defaults = None
        if armor_label:
            conn = get_connection(DB_PATH)
            try:
                defaults = get_armor_defaults(conn, armor_label)
            finally:
                conn.close()
        select_search_batch(batch_id, defaults)

    def on_batch_deleted() -> None:
        """履歴タブでのバッチ削除時に外部から呼ばれる。バッチ一覧を最新化し、
        削除されたバッチの内容が回収確認パネルに残らないよう念のため閉じる。
        """
        refresh_search_filters()
        close_collection_panel()

    history_view, refresh_history_batches = build_history_view(
        page,
        DB_PATH,
        on_batch_deleted=on_batch_deleted,
        on_batch_selected=go_to_search_with_batch,
        on_collection_check=open_collection_panel,
    )

    def on_imported(batch_id: int) -> None:
        refresh_search_filters()
        refresh_history_batches()

    import_view = build_import_view(
        page, DB_PATH, on_imported=on_imported, on_show_results=go_to_search_after_import
    )

    settings_view, refresh_settings_view = build_settings_view(page, DB_PATH)
    contact_view = build_contact_view(page, DB_PATH)

    def on_tabs_change(e: ft.Event[ft.Tabs]) -> None:
        # 設定タブに切り替わるたびに表示中の項目を読み直し、検索タブでの
        # スキル集合の作成・削除や取込タブでの防具追加など、他タブでの
        # 変更を反映する（例: 新しく作ったスキル集合が防具ごとの検索初期
        # 設定のドロップダウンに出てこない、という不具合の対策）。
        if tabs_control.selected_index == SETTINGS_TAB_INDEX:
            refresh_settings_view()

    tabs_control = ft.Tabs(
        length=5,
        expand=True,
        on_change=on_tabs_change,
        content=ft.Column(
            expand=True,
            controls=[
                ft.TabBar(
                    tabs=[
                        ft.Tab(label="取込"),
                        ft.Tab(label="検索"),
                        ft.Tab(label="履歴"),
                        ft.Tab(label="設定"),
                        ft.Tab(label="お問い合わせ"),
                    ]
                ),
                ft.TabBarView(
                    expand=True,
                    controls=[
                        import_view,
                        search_view,
                        history_view,
                        settings_view,
                        contact_view,
                    ],
                ),
            ],
        ),
    )
    page.add(ft.Row([tabs_control, collection_panel], expand=True, spacing=0))

    # --- キーボードのPageUp/PageDownで、表示中のタブをスクロールする ---
    # 矢印キー（上下）はドロップダウンの選択肢移動などコントロール側でも使われており、
    # 開いている間はページスクロールを確実に防げないため見送った
    # （PageUp/PageDownはどのコントロールも内部で使っていないため競合しない）。
    _PAGE_KEY_STEP = 400  # PageUp/PageDownキー1回あたりのスクロール量(px)

    _tab_views = [
        import_view,
        search_view,
        history_view,
        settings_view,
        contact_view,
    ]

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
    def apply_dont_show_again(checkbox: ft.Checkbox) -> None:
        if checkbox.value:
            conn = get_connection(DB_PATH)
            try:
                set_update_check_enabled(conn, False)
            finally:
                conn.close()

    def show_update_dialog(latest_tag: str) -> None:
        dont_show_again_checkbox = ft.Checkbox(
            label="次からは表示しない（設定タブでいつでも変更できます）"
        )

        async def on_yes(e: ft.Event[ft.Button]) -> None:
            apply_dont_show_again(dont_show_again_checkbox)
            page.pop_dialog()
            await ft.UrlLauncher().launch_url(RELEASE_PAGE_URL)

        def on_no(e: ft.Event[ft.TextButton]) -> None:
            apply_dont_show_again(dont_show_again_checkbox)
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("新しいバージョンがあります"),
            content=ft.Column(
                [
                    ft.Text(
                        f"現在のバージョン: {APP_VERSION}\n最新バージョン: {latest_tag}\n\n"
                        "ダウンロードページを開きますか？"
                    ),
                    dont_show_again_checkbox,
                ],
                tight=True,
            ),
            actions=[
                ft.TextButton(content="いいえ", on_click=on_no),
                ft.Button(content="はい", on_click=on_yes),
            ],
        )
        page.show_dialog(dialog)
        page.update()

    def check_for_update() -> None:
        conn = get_connection(DB_PATH)
        try:
            enabled = is_update_check_enabled(conn)
        finally:
            conn.close()
        if not enabled:
            return

        latest_tag = fetch_latest_release_tag()
        if latest_tag is not None and is_update_available(APP_VERSION, latest_tag):
            show_update_dialog(latest_tag)

    page.run_thread(check_for_update)


if __name__ == "__main__":
    ft.run(main)
