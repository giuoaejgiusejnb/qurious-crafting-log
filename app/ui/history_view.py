from pathlib import Path
from typing import Callable

import flet as ft

from app.core.history import delete_batch, list_batches
from app.db.connection import get_connection


def build_history_view(
    page: ft.Page,
    db_path: Path,
    on_batch_deleted: Callable[[], None] | None = None,
    on_batch_selected: Callable[[int], None] | None = None,
    on_collection_check: Callable[[int], None] | None = None,
) -> tuple[ft.Control, Callable[[], None]]:
    """履歴画面を構築する。戻り値は (画面コントロール, バッチ一覧を最新化する関数)。

    on_batch_deletedはバッチ削除時に呼ばれ、他タブのバッチ一覧更新に使う。
    on_batch_selectedはバッチ行クリック時にバッチIDを渡して呼ばれ、
    検索タブへの遷移（対象バッチとして検索実行）に使う。
    on_collection_checkは「回収確認」ボタン押下時にバッチIDを渡して呼ばれ、
    回収確認サイドパネル（試作）の表示に使う。
    """
    batch_list_column = ft.Column(spacing=2)

    def confirm_delete_batch(batch_id: int) -> None:
        def do_delete(e: ft.Event[ft.Button]) -> None:
            conn = get_connection(db_path)
            try:
                delete_batch(conn, batch_id)
            finally:
                conn.close()
            page.pop_dialog()
            load_batches()
            if on_batch_deleted is not None:
                on_batch_deleted()
            page.update()

        def cancel_delete(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("削除の確認"),
            content=ft.Text(f"バッチ #{batch_id} を削除しますか？この操作は取り消せません。"),
            actions=[
                ft.TextButton(content="キャンセル", on_click=cancel_delete),
                ft.Button(content="削除する", on_click=do_delete),
            ],
        )
        page.show_dialog(confirm_dialog)

    def on_batch_row_click(batch_id: int) -> None:
        if on_batch_selected is not None:
            on_batch_selected(batch_id)

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
                ft.Text("", width=60, weight=ft.FontWeight.BOLD),
            ]
        )
        batch_list_column.controls.append(header)
        batch_list_column.controls.append(ft.Divider(height=1))

        for index, batch in enumerate(batches):
            batch_list_column.controls.append(
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Text(f"#{batch.id}", width=100),
                                    ft.Text(batch.imported_at, width=160),
                                    ft.Text(batch.label or "", width=140),
                                    ft.Text(str(batch.row_count), width=80),
                                ]
                            ),
                            on_click=lambda e, bid=batch.id: on_batch_row_click(bid),
                            bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST if index % 2 == 1 else None,
                            padding=ft.Padding.symmetric(vertical=4, horizontal=4),
                        ),
                        ft.TextButton(
                            content="回収確認",
                            on_click=lambda e, bid=batch.id: (
                                on_collection_check(bid) if on_collection_check else None
                            ),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            tooltip="このバッチを削除",
                            icon_color=ft.Colors.RED_400,
                            on_click=lambda e, bid=batch.id: confirm_delete_batch(bid),
                        ),
                    ],
                    spacing=0,
                )
            )

    def refresh_batches() -> None:
        """バッチ一覧を最新化する。取込タブでの取込完了時に外部から呼ばれる（自動更新）。

        ページ接続後にのみ呼ばれる想定（page.update()を呼ぶため）。
        """
        load_batches()
        page.update()

    load_batches()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    view = ft.Column(
        [
            ft.Text("取込履歴", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("バッチをクリックすると、検索タブでそのバッチを対象に検索します。"),
            ft.Container(content=batch_list_column, padding=ft.Padding.symmetric(vertical=8)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return view, refresh_batches
