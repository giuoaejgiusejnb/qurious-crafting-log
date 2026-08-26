from pathlib import Path

import flet as ft

from app.core.history import fetch_batch_results, list_batches
from app.core.search import fetch_skill_breakdown
from app.db.connection import get_connection

_PAGE_SIZE = 200


def build_history_view(page: ft.Page, db_path: Path) -> ft.Control:
    batch_list_column = ft.Column(spacing=2)
    results_column = ft.Column(spacing=2)
    detail_status_text = ft.Text()

    selected_batch_id: int | None = None
    selected_batch_row_count: int = 0
    current_offset: int = 0

    prev_button = ft.Button(content="前へ")
    next_button = ft.Button(content="次へ")

    def render_results_page() -> None:
        results_column.controls.clear()

        if selected_batch_id is None:
            page.update()
            return

        conn = get_connection(db_path)
        try:
            rows = fetch_batch_results(conn, selected_batch_id, limit=_PAGE_SIZE, offset=current_offset)
            breakdown = fetch_skill_breakdown(conn, [r.id for r in rows])
        finally:
            conn.close()

        if not rows:
            results_column.controls.append(ft.Text("このバッチにはデータがありません"))
        else:
            header = ft.Row(
                [
                    ft.Text("ID", width=60, weight=ft.FontWeight.BOLD),
                    ft.Text("スキル", width=240, weight=ft.FontWeight.BOLD),
                    ft.Text("合計値", width=60, weight=ft.FontWeight.BOLD),
                    ft.Text("total_cost", width=100, weight=ft.FontWeight.BOLD),
                    ft.Text("zeny", width=80, weight=ft.FontWeight.BOLD),
                ]
            )
            results_column.controls.append(header)
            results_column.controls.append(ft.Divider(height=1))
            for row in rows:
                skills_text = "、".join(f"{name}+{value}" for name, value in breakdown.get(row.id, []))
                results_column.controls.append(
                    ft.Row(
                        [
                            ft.Text(str(row.id), width=60),
                            ft.Text(skills_text, width=240),
                            ft.Text(str(row.skill_sum), width=60),
                            ft.Text(str(row.total_cost), width=100),
                            ft.Text(str(row.zeny), width=80),
                        ]
                    )
                )

        start = current_offset + 1
        end = current_offset + len(rows)
        detail_status_text.value = (
            f"バッチ #{selected_batch_id}: {start}〜{end}件 / 全{selected_batch_row_count}件"
            if rows
            else f"バッチ #{selected_batch_id}: データなし"
        )
        prev_button.disabled = current_offset <= 0
        next_button.disabled = end >= selected_batch_row_count
        page.update()

    def open_batch(batch_id: int, row_count: int) -> None:
        nonlocal selected_batch_id, selected_batch_row_count, current_offset
        selected_batch_id = batch_id
        selected_batch_row_count = row_count
        current_offset = 0
        render_results_page()

    def go_prev(e: ft.Event[ft.Button]) -> None:
        nonlocal current_offset
        current_offset = max(0, current_offset - _PAGE_SIZE)
        render_results_page()

    def go_next(e: ft.Event[ft.Button]) -> None:
        nonlocal current_offset
        current_offset += _PAGE_SIZE
        render_results_page()

    prev_button.on_click = go_prev
    next_button.on_click = go_next

    def load_batches() -> None:
        conn = get_connection(db_path)
        try:
            batches = list_batches(conn)
        finally:
            conn.close()

        batch_list_column.controls.clear()
        if not batches:
            batch_list_column.controls.append(ft.Text("まだ取込履歴がありません"))
            return

        header = ft.Row(
            [
                ft.Text("バッチID", width=100, weight=ft.FontWeight.BOLD),
                ft.Text("取込日時", width=160, weight=ft.FontWeight.BOLD),
                ft.Text("防具", width=140, weight=ft.FontWeight.BOLD),
                ft.Text("件数", width=80, weight=ft.FontWeight.BOLD),
            ]
        )
        batch_list_column.controls.append(header)
        batch_list_column.controls.append(ft.Divider(height=1))

        for batch in batches:
            batch_list_column.controls.append(
                ft.Row(
                    [
                        ft.TextButton(
                            content=f"#{batch.id}",
                            width=100,
                            on_click=lambda e, bid=batch.id, count=batch.row_count: open_batch(bid, count),
                        ),
                        ft.Text(batch.imported_at, width=160),
                        ft.Text(batch.label or "", width=140),
                        ft.Text(str(batch.row_count), width=80),
                    ]
                )
            )

    def refresh_batches(e: ft.Event[ft.Button] | None = None) -> None:
        load_batches()
        if e is not None:
            page.update()

    refresh_button = ft.Button(content="履歴を更新")
    refresh_button.on_click = refresh_batches

    refresh_batches()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    return ft.Column(
        [
            ft.Text("取込履歴", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([refresh_button]),
            ft.Container(content=batch_list_column, padding=ft.Padding.symmetric(vertical=8)),
            ft.Divider(),
            ft.Text("バッチの内容", size=16, weight=ft.FontWeight.BOLD),
            detail_status_text,
            ft.Row([prev_button, next_button]),
            ft.Container(content=results_column, expand=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
