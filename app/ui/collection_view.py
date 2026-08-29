from pathlib import Path
from typing import Callable

import flet as ft

from app.core.collection import CollectionLimitError, fetch_collected_in_batch, set_collected
from app.core.history import list_batches
from app.core.search import fetch_skill_breakdown
from app.db.connection import get_connection
from app.ui.skills_display import build_skills_wrap

_UNSELECTED = "__unselected__"


def build_collection_view(page: ft.Page, db_path: Path) -> tuple[ft.Control, Callable[[], None]]:
    """回収確認画面を構築する。戻り値は (画面コントロール, バッチ選択肢を最新化する関数)。"""
    status_text = ft.Text()
    results_list = ft.Column(spacing=2)

    batch_dropdown = ft.Dropdown(
        label="バッチを選択",
        width=420,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    def refresh_batch_options() -> None:
        conn = get_connection(db_path)
        try:
            batches = list_batches(conn)
        finally:
            conn.close()

        batch_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[
                ft.DropdownOption(
                    key=str(b.id), text=f"#{b.id} {b.imported_at} {b.label or ''}".strip()
                )
                for b in batches
            ],
        ]
        if batch_dropdown.value not in {opt.key for opt in batch_dropdown.options}:
            batch_dropdown.value = _UNSELECTED

    refresh_batch_options()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

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
                load_selected_batch()  # チェックを外したら一覧から消す（page.update()も内部で行う）
            else:
                page.update()

        checkbox.on_change = on_change
        return checkbox

    def render_results(
        rows, breakdown: dict[int, list[tuple[str, int]]], batch_id: int
    ) -> None:
        results_list.controls.clear()

        if not rows:
            results_list.controls.append(ft.Text("このバッチに回収済みの結果はありません"))
            page.update()
            return

        header = ft.Row(
            [
                ft.Text("練成回数", width=70, weight=ft.FontWeight.BOLD),
                ft.Text("ゼニー", width=80, weight=ft.FontWeight.BOLD),
                ft.Text("コスト", width=80, weight=ft.FontWeight.BOLD),
                ft.Text("スキル", width=240, weight=ft.FontWeight.BOLD),
                ft.Text("スロット", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("耐性", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("スキル欠け", width=80, weight=ft.FontWeight.BOLD),
                ft.Text("回収", width=60, weight=ft.FontWeight.BOLD),
            ]
        )
        results_list.controls.append(header)
        results_list.controls.append(ft.Divider(height=1))

        for index, row in enumerate(rows):
            results_list.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Text(str(row.zeny_count), width=70),
                            ft.Text(str(row.zeny), width=80),
                            ft.Text(str(row.total_cost), width=80),
                            build_skills_wrap(breakdown.get(row.id, [])),
                            ft.Text(str(row.slot_add), width=60),
                            ft.Text(str(row.print_resistance), width=60),
                            ft.Text("有" if row.has_deficiency else "無", width=80),
                            make_collected_checkbox(row.id, batch_id),
                        ]
                    ),
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST if index % 2 == 1 else None,
                    padding=ft.Padding.symmetric(vertical=2, horizontal=4),
                )
            )
        page.update()

    def load_selected_batch() -> None:
        if not batch_dropdown.value or batch_dropdown.value == _UNSELECTED:
            results_list.controls.clear()
            status_text.value = "バッチを選択してください"
            page.update()
            return

        batch_id = int(batch_dropdown.value)
        conn = get_connection(db_path)
        try:
            rows = fetch_collected_in_batch(conn, batch_id)
            breakdown = fetch_skill_breakdown(conn, [r.id for r in rows])
        finally:
            conn.close()

        status_text.value = f"バッチ #{batch_id}: 回収済み{len(rows)}件"
        page.update()
        render_results(rows, breakdown, batch_id)

    def on_batch_select(e: ft.Event[ft.Dropdown]) -> None:
        load_selected_batch()

    batch_dropdown.on_select = on_batch_select

    view = ft.Column(
        [
            ft.Text("回収確認", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("バッチを選択すると、そのバッチ内で回収チェック済みの結果が表示されます。"),
            ft.Row([batch_dropdown]),
            status_text,
            ft.Divider(),
            results_list,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return view, refresh_batch_options
