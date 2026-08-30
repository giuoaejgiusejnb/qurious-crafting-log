from pathlib import Path

import flet as ft

# 設定タブ内の縦向きナビゲーション（NavigationRail）に並べる項目。
# 現時点ではまだ実際の設定項目が決まっていないため、器（枠組み）として
# 「項目1」「項目2」「項目3」のプレースホルダーを用意している。
# 今後、設定項目が決まり次第、ここに追加していく。
_SETTINGS_ITEMS: list[tuple[str, str, str]] = [
    ("項目1", ft.Icons.SETTINGS_OUTLINED, "項目1の内容（準備中）"),
    ("項目2", ft.Icons.SETTINGS_OUTLINED, "項目2の内容（準備中）"),
    ("項目3", ft.Icons.SETTINGS_OUTLINED, "項目3の内容（準備中）"),
]


def build_settings_view(page: ft.Page, db_path: Path) -> ft.Control:
    """設定画面を構築する。

    左側に縦向きのナビゲーション（NavigationRail）、右側に選択中の項目の
    内容を表示する2カラム構成。
    """
    content_area = ft.Container(expand=True, padding=16)

    def build_item_content(index: int) -> ft.Control:
        label, _icon, body = _SETTINGS_ITEMS[index]
        return ft.Column(
            [
                ft.Text(label, size=18, weight=ft.FontWeight.BOLD),
                ft.Text(body),
            ]
        )

    def show_item(index: int) -> None:
        content_area.content = build_item_content(index)

    def on_rail_change(e: ft.Event[ft.NavigationRail]) -> None:
        show_item(nav_rail.selected_index or 0)
        page.update()

    nav_rail = ft.NavigationRail(
        selected_index=0,
        label_type=ft.NavigationRailLabelType.ALL,
        min_width=100,
        destinations=[
            ft.NavigationRailDestination(icon=icon, label=label)
            for label, icon, _body in _SETTINGS_ITEMS
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
