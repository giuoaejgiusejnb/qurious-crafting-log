from pathlib import Path

import flet as ft

from app.core.importer import import_block
from app.db.connection import get_connection


def build_import_view(page: ft.Page, db_path: Path) -> ft.Control:
    log_field = ft.TextField(
        label="result_log（複数行貼り付け可）",
        multiline=True,
        min_lines=10,
        max_lines=16,
        expand=True,
    )
    label_field = ft.TextField(label="メモ（任意）", width=400)
    progress_bar = ft.ProgressBar(width=400, value=0, visible=False)
    status_text = ft.Text()
    import_button = ft.Button(content="取込")

    def set_busy(busy: bool) -> None:
        import_button.disabled = busy
        progress_bar.visible = busy
        page.update()

    def report_progress(done: int, total: int) -> None:
        progress_bar.value = done / total if total else 1
        status_text.value = f"取込中... {done}/{total}"
        page.update()

    def run_import() -> None:
        text = log_field.value or ""
        label = label_field.value or None

        if not text.strip():
            status_text.value = "result_logを入力してください"
            page.update()
            return

        set_busy(True)
        progress_bar.value = 0
        status_text.value = "取込を開始しました..."
        page.update()

        conn = get_connection(db_path)
        try:
            summary = import_block(conn, text, label, progress_callback=report_progress)
        finally:
            conn.close()

        status_text.value = (
            f"取込完了: 成功 {summary.imported_count}件 / エラー {summary.error_count}件"
            f"（バッチID: {summary.batch_id}）"
        )
        if summary.errors:
            preview = "、".join(f"{ln}行目: {msg}" for ln, msg in summary.errors[:5])
            status_text.value += f"\nエラー例: {preview}"

        log_field.value = ""
        set_busy(False)

    def on_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_import)

    import_button.on_click = on_click

    return ft.Column(
        [
            ft.Text("錬成結果の取込", size=20, weight=ft.FontWeight.BOLD),
            log_field,
            label_field,
            ft.Row([import_button]),
            progress_bar,
            status_text,
        ],
        expand=True,
    )
