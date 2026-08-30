import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Callable

import flet as ft

from app.core.armor_defaults import ArmorSearchDefaults, get_armor_defaults, set_armor_defaults
from app.core.backup import backup_database, restore_database
from app.core.equipment import list_all_equipment_options
from app.core.search import COST_OPTIONS, DEFAULT_SORT, RESISTANCE_OPTIONS
from app.core.skill_sets import list_skill_set_names
from app.core.update_check import is_update_check_enabled, set_update_check_enabled
from app.db.connection import get_connection

_UNSELECTED = "__unselected__"


def build_settings_view(page: ft.Page, db_path: Path) -> tuple[ft.Control, Callable[[], None]]:
    """設定画面を構築する。戻り値は (画面コントロール, 表示中の項目を読み直す関数)。

    左側に縦向きのナビゲーション（NavigationRail）、右側に選択中の項目の
    内容を表示する2カラム構成。
    """
    content_area = ft.Container(expand=True, padding=16)

    def build_update_check_content() -> ft.Control:
        conn = get_connection(db_path)
        try:
            enabled = is_update_check_enabled(conn)
        finally:
            conn.close()

        def on_change(e: ft.Event[ft.Checkbox]) -> None:
            conn = get_connection(db_path)
            try:
                set_update_check_enabled(conn, checkbox.value)
            finally:
                conn.close()

        checkbox = ft.Checkbox(
            label="起動時に新しいバージョンがないか確認する",
            value=enabled,
            on_change=on_change,
        )
        return ft.Column(
            [
                ft.Text("更新チェック", size=18, weight=ft.FontWeight.BOLD),
                checkbox,
            ]
        )

    def build_armor_defaults_content() -> ft.Control:
        """防具ごとの検索初期設定。

        取込タブでの取込完了後、検索タブへ自動遷移する際に使われる初期条件を
        防具ごとに登録できるようにする（履歴タブからの遷移では使われず、
        従来通り全条件がリセットされる）。
        """
        conn = get_connection(db_path)
        try:
            armor_options = list_all_equipment_options(conn)
        finally:
            conn.close()

        status_text = ft.Text(size=12)
        detail_area = ft.Container()

        armor_dropdown = ft.Dropdown(
            label="防具",
            width=220,
            value=armor_options[0] if armor_options else None,
            options=[ft.DropdownOption(key=a, text=a) for a in armor_options],
        )

        def load_armor_detail(armor_name: str) -> None:
            conn = get_connection(db_path)
            try:
                defaults = get_armor_defaults(conn, armor_name)
                skill_set_names = list_skill_set_names(conn)
            finally:
                conn.close()

            skill_set_dropdown = ft.Dropdown(
                label="スキル集合",
                width=220,
                value=defaults.skill_set_name or _UNSELECTED,
                options=[
                    ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
                    *[ft.DropdownOption(key=n, text=n) for n in skill_set_names],
                ],
            )
            threshold_dropdown = ft.Dropdown(
                label="必要な個数（1〜4）",
                width=160,
                value=str(defaults.threshold),
                options=[ft.DropdownOption(key=str(n), text=str(n)) for n in (1, 2, 3, 4)],
            )
            cost_min_dropdown = ft.Dropdown(
                label="コスト以上",
                width=140,
                value=str(defaults.min_total_cost),
                options=[ft.DropdownOption(key=n, text=n) for n in COST_OPTIONS],
            )
            cost_max_dropdown = ft.Dropdown(
                label="コスト以下",
                width=140,
                value=str(defaults.max_total_cost),
                options=[ft.DropdownOption(key=n, text=n) for n in COST_OPTIONS],
            )
            resistance_min_dropdown = ft.Dropdown(
                label="耐性以上",
                width=140,
                value=(
                    str(defaults.min_resistance)
                    if defaults.min_resistance is not None
                    else _UNSELECTED
                ),
                options=[
                    ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
                    *[ft.DropdownOption(key=n, text=n) for n in RESISTANCE_OPTIONS],
                ],
            )
            resistance_max_dropdown = ft.Dropdown(
                label="耐性以下",
                width=140,
                value=(
                    str(defaults.max_resistance)
                    if defaults.max_resistance is not None
                    else _UNSELECTED
                ),
                options=[
                    ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
                    *[ft.DropdownOption(key=n, text=n) for n in RESISTANCE_OPTIONS],
                ],
            )
            deficiency_dropdown = ft.Dropdown(
                label="スキル欠けの有無",
                width=160,
                value=(
                    str(defaults.has_deficiency)
                    if defaults.has_deficiency is not None
                    else _UNSELECTED
                ),
                options=[
                    ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
                    ft.DropdownOption(key="1", text="有"),
                    ft.DropdownOption(key="0", text="無"),
                ],
            )
            sort_dropdown = ft.Dropdown(
                label="並び替え",
                width=220,
                value=defaults.sort,
                options=[
                    ft.DropdownOption(key="craft_order", text="練成順"),
                    ft.DropdownOption(key="total_cost_desc", text="コスト（降順）"),
                ],
            )

            def do_save(e: ft.Event[ft.Button]) -> None:
                try:
                    min_cost = int(cost_min_dropdown.value)
                    max_cost = int(cost_max_dropdown.value)
                except (TypeError, ValueError):
                    status_text.value = "コストの指定が不正です"
                    page.update()
                    return
                if min_cost > max_cost:
                    status_text.value = "「コスト以上」は「コスト以下」より大きくできません"
                    page.update()
                    return

                min_res = (
                    int(resistance_min_dropdown.value)
                    if resistance_min_dropdown.value
                    and resistance_min_dropdown.value != _UNSELECTED
                    else None
                )
                max_res = (
                    int(resistance_max_dropdown.value)
                    if resistance_max_dropdown.value
                    and resistance_max_dropdown.value != _UNSELECTED
                    else None
                )
                if min_res is not None and max_res is not None and min_res > max_res:
                    status_text.value = "「耐性以上」は「耐性以下」より大きくできません"
                    page.update()
                    return

                new_defaults = ArmorSearchDefaults(
                    skill_set_name=(
                        skill_set_dropdown.value
                        if skill_set_dropdown.value and skill_set_dropdown.value != _UNSELECTED
                        else None
                    ),
                    threshold=int(threshold_dropdown.value or 1),
                    min_total_cost=min_cost,
                    max_total_cost=max_cost,
                    min_resistance=min_res,
                    max_resistance=max_res,
                    has_deficiency=(
                        int(deficiency_dropdown.value)
                        if deficiency_dropdown.value and deficiency_dropdown.value != _UNSELECTED
                        else None
                    ),
                    sort=sort_dropdown.value or DEFAULT_SORT,
                )
                conn = get_connection(db_path)
                try:
                    set_armor_defaults(conn, armor_name, new_defaults)
                finally:
                    conn.close()
                status_text.value = f"「{armor_name}」の初期設定を保存しました"
                page.update()

            def do_reset(e: ft.Event[ft.TextButton]) -> None:
                # 画面表示のみを既定値に戻す（保存はしない）。他の項目と同様、
                # 確定するには「保存」を押す必要がある
                # （誤操作で保存済みの設定が即座に消えてしまわないようにするため）。
                defaults = ArmorSearchDefaults()
                skill_set_dropdown.value = defaults.skill_set_name or _UNSELECTED
                threshold_dropdown.value = str(defaults.threshold)
                cost_min_dropdown.value = str(defaults.min_total_cost)
                cost_max_dropdown.value = str(defaults.max_total_cost)
                resistance_min_dropdown.value = (
                    str(defaults.min_resistance)
                    if defaults.min_resistance is not None
                    else _UNSELECTED
                )
                resistance_max_dropdown.value = (
                    str(defaults.max_resistance)
                    if defaults.max_resistance is not None
                    else _UNSELECTED
                )
                deficiency_dropdown.value = (
                    str(defaults.has_deficiency)
                    if defaults.has_deficiency is not None
                    else _UNSELECTED
                )
                sort_dropdown.value = defaults.sort
                status_text.value = "既定値を表示しました（保存するには「保存」を押してください）"
                page.update()

            detail_area.content = ft.Column(
                [
                    ft.Row([skill_set_dropdown, threshold_dropdown]),
                    ft.Row([cost_min_dropdown, cost_max_dropdown]),
                    ft.Row([resistance_min_dropdown, resistance_max_dropdown]),
                    ft.Row([deficiency_dropdown]),
                    ft.Row([sort_dropdown]),
                    ft.Row(
                        [
                            ft.Button(content="保存", on_click=do_save),
                            ft.TextButton(content="既定値に戻す", on_click=do_reset),
                        ]
                    ),
                ],
                spacing=8,
            )

        def on_armor_select(e: ft.Event[ft.Dropdown]) -> None:
            status_text.value = ""
            if armor_dropdown.value:
                load_armor_detail(armor_dropdown.value)
            page.update()

        armor_dropdown.on_select = on_armor_select

        if armor_options:
            load_armor_detail(armor_options[0])

        return ft.Column(
            [
                ft.Text("防具ごとの検索初期設定", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "取込タブから検索タブへ自動的に移動するときに使う初期条件を、"
                    "防具ごとに登録できます（履歴タブからの移動では使われません。"
                    "そちらは常に全条件がリセットされます）。"
                ),
                armor_dropdown,
                status_text,
                detail_area,
            ],
            spacing=8,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def build_backup_content() -> ft.Control:
        """DBファイルのバックアップ・復元（実処理はapp/core/backup.pyに集約）。"""
        status_text = ft.Text(size=12)

        async def do_backup(e: ft.Event[ft.Button]) -> None:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            dest_path = await ft.FilePicker().save_file(
                dialog_title="バックアップの保存先を選択",
                file_name=f"qurious_crafting_log_backup_{timestamp}.db",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["db"],
            )
            if not dest_path:
                return  # キャンセル

            try:
                backup_database(db_path, dest_path)
            except sqlite3.Error as exc:
                status_text.value = f"バックアップに失敗しました: {exc}"
                page.update()
                return

            status_text.value = f"バックアップを保存しました: {dest_path}"
            page.update()

        def perform_restore(source_path: str) -> None:
            try:
                safety_backup_path = restore_database(db_path, source_path)
            except (OSError, sqlite3.Error) as exc:
                status_text.value = f"復元に失敗しました: {exc}"
                page.update()
                return

            status_text.value = (
                "復元しました。反映するにはアプリを再起動してください。"
                f"（復元前のデータは {safety_backup_path.name} として保存しています）"
            )
            page.update()

        def confirm_restore(source_path: str) -> None:
            def do_confirm(e: ft.Event[ft.Button]) -> None:
                page.pop_dialog()
                perform_restore(source_path)

            def cancel(e: ft.Event[ft.TextButton]) -> None:
                page.pop_dialog()

            dialog = ft.AlertDialog(
                modal=True,
                title=ft.Text("復元の確認"),
                content=ft.Text(
                    "選択したバックアップの内容で、現在のデータをすべて上書きします。\n"
                    "念のため、現在のデータも復元前に自動でバックアップします。\n"
                    "復元後はアプリの再起動が必要です。よろしいですか？"
                ),
                actions=[
                    ft.TextButton(content="キャンセル", on_click=cancel),
                    ft.Button(content="復元する", on_click=do_confirm),
                ],
            )
            page.show_dialog(dialog)

        async def do_restore(e: ft.Event[ft.Button]) -> None:
            files = await ft.FilePicker().pick_files(
                dialog_title="復元するバックアップファイルを選択",
                file_type=ft.FilePickerFileType.CUSTOM,
                allowed_extensions=["db"],
            )
            if not files:
                return  # キャンセル
            picked_path = files[0].path
            if not picked_path:
                status_text.value = "選択したファイルのパスを取得できませんでした"
                page.update()
                return
            confirm_restore(picked_path)

        return ft.Column(
            [
                ft.Text("バックアップ", size=18, weight=ft.FontWeight.BOLD),
                ft.Text(
                    "取込結果や回収チェックなど、このアプリのデータをまとめて"
                    "1つのファイルに保存・復元できます。"
                ),
                ft.Row([ft.Button(content="バックアップを保存", on_click=do_backup)]),
                ft.Row([ft.Button(content="バックアップから復元", on_click=do_restore)]),
                status_text,
            ],
            spacing=8,
        )

    # 設定タブ内の縦向きナビゲーション（NavigationRail）に並べる項目。
    items: list[tuple[str, str, Callable[[], ft.Control]]] = [
        ("更新チェック", ft.Icons.SYSTEM_UPDATE_OUTLINED, build_update_check_content),
        ("防具ごとの検索初期設定", ft.Icons.TUNE_OUTLINED, build_armor_defaults_content),
        ("バックアップ", ft.Icons.SAVE_OUTLINED, build_backup_content),
    ]

    def show_item(index: int) -> None:
        _label, _icon, build_content = items[index]
        content_area.content = build_content()

    def on_rail_change(e: ft.Event[ft.NavigationRail]) -> None:
        show_item(nav_rail.selected_index or 0)
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        destinations=[
            ft.NavigationRailDestination(icon=icon, label=label) for label, icon, _build in items
        ],
        on_change=on_rail_change,
    )

    show_item(0)  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    def refresh() -> None:
        """表示中の項目を読み直す。設定タブがアプリの他タブから選ばれるたびに
        main.py側から呼ばれ、検索タブでのスキル集合の作成・削除や取込タブでの
        防具追加など、他タブでの変更を反映する（ページ接続後にのみ呼ばれる想定）。
        """
        show_item(nav_rail.selected_index or 0)
        page.update()

    view = ft.Row(
        [
            nav_rail,
            ft.VerticalDivider(width=1),
            content_area,
        ],
        expand=True,
    )
    return view, refresh
