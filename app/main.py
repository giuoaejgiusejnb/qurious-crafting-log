from pathlib import Path

import flet as ft

from app.ui.import_view import build_import_view
from app.ui.search_view import build_search_view

DB_PATH = Path(__file__).resolve().parent.parent / "data" / "qurious_crafting_log.db"


def main(page: ft.Page) -> None:
    page.title = "モンハン錬成結果 記録・検索"
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)

    page.add(
        ft.Tabs(
            length=2,
            expand=True,
            content=ft.Column(
                expand=True,
                controls=[
                    ft.TabBar(
                        tabs=[
                            ft.Tab(label="取込"),
                            ft.Tab(label="検索"),
                        ]
                    ),
                    ft.TabBarView(
                        expand=True,
                        controls=[
                            build_import_view(page, DB_PATH),
                            build_search_view(page, DB_PATH),
                        ],
                    ),
                ],
            ),
        )
    )


if __name__ == "__main__":
    ft.run(main)
