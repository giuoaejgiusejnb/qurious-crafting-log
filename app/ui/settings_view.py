from pathlib import Path
from typing import Callable

import flet as ft

from app.core.update_check import is_update_check_enabled, set_update_check_enabled
from app.db.connection import get_connection


def build_settings_view(page: ft.Page, db_path: Path) -> ft.Control:
    """設定画面を構築する。

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

    def build_placeholder_content(label: str) -> ft.Control:
        return ft.Column(
            [
                ft.Text(label, size=18, weight=ft.FontWeight.BOLD),
                ft.Text(f"{label}の内容（準備中）"),
            ]
        )

    # 設定タブ内の縦向きナビゲーション（NavigationRail）に並べる項目。
    # 「更新チェック」以外はまだ実際の設定項目が決まっていないため、
    # 器（枠組み）としてプレースホルダーを用意している。
    items: list[tuple[str, str, Callable[[], ft.Control]]] = [
        ("更新チェック", ft.Icons.SYSTEM_UPDATE_OUTLINED, build_update_check_content),
        ("項目2", ft.Icons.SETTINGS_OUTLINED, lambda: build_placeholder_content("項目2")),
        ("項目3", ft.Icons.SETTINGS_OUTLINED, lambda: build_placeholder_content("項目3")),
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

    return ft.Row(
        [
            nav_rail,
            ft.VerticalDivider(width=1),
            content_area,
        ],
        expand=True,
    )
