from pathlib import Path

import flet as ft

from app.ui.history_view import build_history_view
from app.ui.import_view import build_import_view
from app.ui.search_view import build_search_view

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "qurious_crafting_log.db"


def main(page: ft.Page) -> None:
    page.title = "モンハン錬成結果 記録・検索"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

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

    page.add(
        ft.Tabs(
            length=3,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label="取込"),
                            ft.Tab(label="検索"),
                            ft.Tab(label="履歴"),
                        ]
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            build_import_view(page, DB_PATH),
                            build_search_view(page, DB_PATH),
                            build_history_view(page, DB_PATH),
                        ],
                    ),
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
