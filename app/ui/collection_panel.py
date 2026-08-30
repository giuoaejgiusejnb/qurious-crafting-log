from collections.abc import Callable
from pathlib import Path

import flet as ft

from app.core.collection import (
    CollectionLimitError,
    fetch_collected_in_batch,
    set_collected,
)
from app.core.search import fetch_skill_breakdown
from app.db.connection import get_connection
from app.ui.skills_display import build_skills_wrap

_PANEL_WIDTH = 260
_SKILLS_WRAP_WIDTH = 220


def build_collection_panel(
    page: ft.Page, db_path: Path
) -> tuple[ft.Control, Callable[[int], None], Callable[[], None]]:
    """回収確認サイドパネルを構築する。

    タブの切り替えとは独立して画面の横に居座り、どのタブを表示していても
    回収状況を見比べられるようにするためのパネル（visibleの切り替えで開閉）。
    戻り値は (パネルのコントロール, 指定バッチを開く関数, 閉じる関数)。
    """
    status_text = ft.Text()
    results_list = ft.Column(spacing=2)

    def make_collected_checkbox(result_id: int, batch_id: int) -> ft.Checkbox:
        checkbox = ft.Checkbox(value=True)

        def on_change(e: ft.Event[ft.Checkbox]) -> None:
            conn = get_connection(db_path)
            try:
                try:
                    set_collected(conn, result_id, batch_id, checkbox.value)
                except CollectionLimitError as exc:
                    checkbox.value = False
                    status_text.value = str(exc)
                    page.update()
                    return
            finally:
                conn.close()

            if not checkbox.value:
                render_batch(
                    batch_id
                )  # チェックを外したら一覧から消す（page.update()も内部で行う）
            else:
                page.update()

        checkbox.on_change = on_change
        return checkbox

    def render_batch(batch_id: int) -> None:
        conn = get_connection(db_path)
        try:
            rows = fetch_collected_in_batch(conn, batch_id)
            breakdown = fetch_skill_breakdown(conn, [r.id for r in rows])
        finally:
            conn.close()

        status_text.value = f"バッチ #{batch_id}: 回収予定{len(rows)}件"

        results_list.controls.clear()
        if not rows:
            results_list.controls.append(
                ft.Text("このバッチに回収予定の練成はありません")
            )
            page.update()
            return

        # パネルの幅が狭い（検索タブの回収列が隠れない程度）ため、表形式ではなく
        # 1件ずつカード状に積む表示にする。項目は検索結果一覧からバッチIDと
        # 取込日時を除いたすべて（練成回数・ゼニー・コスト・スキル・スロット・耐性・回収）。
        for index, row in enumerate(rows):
            results_list.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Row(
                                [
                                    ft.Text(
                                        f"練成{row.zeny_count}回目",
                                        weight=ft.FontWeight.BOLD,
                                    ),
                                    make_collected_checkbox(row.id, batch_id),
                                ],
                                alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
                            ),
                            ft.Text(
                                f"ゼニー: {row.zeny}　コスト: {row.total_cost}", size=12
                            ),
                            ft.Text(
                                f"スロット: {row.slot_add}　耐性: {row.print_resistance}",
                                size=12,
                            ),
                            build_skills_wrap(
                                breakdown.get(row.id, []), width=_SKILLS_WRAP_WIDTH
                            ),
                        ],
                        spacing=2,
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST
                    if index % 2 == 1
                    else None,
                    padding=ft.Padding.symmetric(vertical=4, horizontal=4),
                )
            )
            results_list.controls.append(ft.Divider(height=1))
        page.update()

    def close_panel(e: ft.Event[ft.IconButton] | None = None) -> None:
        panel.visible = False
        page.update()

    def open_panel(batch_id: int) -> None:
        panel.visible = True
        render_batch(batch_id)

    panel = ft.Container(
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("回収確認", size=16, weight=ft.FontWeight.BOLD),
                        ft.IconButton(
                            icon=ft.Icons.CLOSE, tooltip="閉じる", on_click=close_panel
                        ),
                    ]
                ),
                status_text,
                ft.Divider(),
                results_list,
            ],
            expand=True,
            scroll=ft.ScrollMode.AUTO,
        ),
        width=_PANEL_WIDTH,
        padding=12,
        bgcolor=ft.Colors.SURFACE_CONTAINER_LOW,
        visible=False,
    )

    return panel, open_panel, close_panel
