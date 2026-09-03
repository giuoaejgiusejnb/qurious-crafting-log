from pathlib import Path
from typing import Callable

import flet as ft

from app.core.history import delete_batch, fetch_batch_errors, list_batches
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
    summary_column = ft.Column(spacing=2)

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

    def show_error_dialog(batch_id: int) -> None:
        conn = get_connection(db_path)
        try:
            errors = fetch_batch_errors(conn, batch_id)
        finally:
            conn.close()

        unparsable_controls: list[ft.Control] = []
        if not errors.unparsable:
            unparsable_controls.append(ft.Text("なし", italic=True))
        else:
            for line_number, zeny_count, reason in errors.unparsable:
                where = f"取込テキスト {line_number}行目"
                if zeny_count is not None:
                    where += f"（回数{zeny_count}）"
                unparsable_controls.append(ft.Text(f"・{where}: {reason}", selectable=True))

        skipped_controls: list[ft.Control] = []
        if not errors.skipped:
            skipped_controls.append(ft.Text("なし", italic=True))
        else:
            for count, zeny in errors.skipped:
                zeny_disp = zeny if zeny is not None else "不明"
                skipped_controls.append(
                    ft.Text(f"練成回数：{count}　　ゼニー：{zeny_disp}", selectable=True)
                )

        content = ft.Column(
            [
                ft.Text("読み込みできなかった行", weight=ft.FontWeight.BOLD),
                *unparsable_controls,
                ft.Divider(),
                ft.Text("飛ばされている練成", weight=ft.FontWeight.BOLD),
                *skipped_controls,
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
            width=560,
            height=420,
        )

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"バッチ #{batch_id} のエラー"),
            content=content,
            actions=[ft.TextButton(content="閉じる", on_click=lambda e: page.pop_dialog())],
        )
        page.show_dialog(dialog)

    def build_error_cell(batch) -> ft.Control:
        if not batch.errors_analyzed:
            # エラー欄の追加前に取り込まれたバッチ。記録が無いことを「—」で示す
            return ft.Container(
                content=ft.Text("—"),
                width=70,
                padding=ft.Padding.only(left=4),
                tooltip="この機能の追加前に取り込まれたバッチのため、エラー記録がありません",
            )
        if batch.error_count == 0:
            return ft.Container(content=ft.Text("0"), width=70, padding=ft.Padding.only(left=4))
        return ft.Container(
            content=ft.TextButton(
                content=f"{batch.error_count}件",
                on_click=lambda e, bid=batch.id: show_error_dialog(bid),
            ),
            width=70,
        )

    def build_summary(batches) -> None:
        """総練成数・防具ごとの練成数を組み立てる（件数0の防具は表示しない）。"""
        total_count = sum(b.row_count for b in batches)

        label_counts: dict[str, int] = {}
        for b in batches:
            if b.label:
                label_counts[b.label] = label_counts.get(b.label, 0) + b.row_count

        summary_column.controls.clear()
        summary_column.controls.append(ft.Text(f"総練成数：{total_count}"))
        summary_column.controls.append(ft.Text("防具ごとの練成数", weight=ft.FontWeight.BOLD))
        if not label_counts:
            summary_column.controls.append(
                ft.Container(content=ft.Text("（防具の記録はまだありません）", italic=True), padding=ft.Padding.only(left=24))
            )
        else:
            for label, count in sorted(label_counts.items()):
                summary_column.controls.append(
                    ft.Container(
                        content=ft.Text(f"{label}の練成数：{count}"),
                        padding=ft.Padding.only(left=24),
                    )
                )

    def load_batches() -> None:
        conn = get_connection(db_path)
        try:
            batches = list_batches(conn)
        finally:
            conn.close()

        build_summary(batches)

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
                ft.Text("エラー", width=70, weight=ft.FontWeight.BOLD),
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
                        build_error_cell(batch),
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
            ft.Text("練成履歴", size=20, weight=ft.FontWeight.BOLD),
            summary_column,
            ft.Divider(),
            ft.Text("取込履歴", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("バッチをクリックすると、検索タブでそのバッチを対象に検索します。"),
            ft.Container(content=batch_list_column, padding=ft.Padding.symmetric(vertical=8)),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return view, refresh_batches
