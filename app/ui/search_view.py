from pathlib import Path

import flet as ft

from app.core.search import SearchParams, fetch_distinct_labels, fetch_skill_breakdown, search_results
from app.core.skill_registry import SkillRegistry
from app.db.connection import get_connection


def _load_skill_names(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT name FROM skills ORDER BY name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def _load_label_options(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    try:
        return fetch_distinct_labels(conn)
    finally:
        conn.close()


def _load_batch_options(db_path: Path) -> list[tuple[int, str]]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute(
            "SELECT id, imported_at, label FROM import_batches ORDER BY id DESC"
        ).fetchall()
        return [
            (batch_id, f"#{batch_id} {imported_at} {label or ''}".strip())
            for batch_id, imported_at, label in rows
        ]
    finally:
        conn.close()


def build_search_view(page: ft.Page, db_path: Path) -> ft.Control:
    skill_checkboxes: dict[str, ft.Checkbox] = {}
    skill_list_container = ft.Container()

    def build_skill_checklist() -> ft.Control:
        names = _load_skill_names(db_path)
        skill_checkboxes.clear()
        if not names:
            return ft.Text("まだスキルが登録されていません（先に取込を行ってください）")
        checkboxes = []
        for name in names:
            checkbox = ft.Checkbox(label=name, value=False)
            skill_checkboxes[name] = checkbox
            checkboxes.append(checkbox)
        return ft.Row(checkboxes, wrap=True)

    def refresh_skill_list(e: ft.Event[ft.Button] | None = None) -> None:
        skill_list_container.content = build_skill_checklist()
        if e is not None:
            page.update()

    refresh_skill_list()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    batch_options = _load_batch_options(db_path)
    batch_dropdown = ft.Dropdown(
        label="対象バッチ（未選択なら全体）",
        width=420,
        options=[ft.DropdownOption(key=str(bid), text=text) for bid, text in batch_options],
    )

    label_options = _load_label_options(db_path)
    label_dropdown = ft.Dropdown(
        label="防具（未選択なら全体）",
        width=220,
        options=[ft.DropdownOption(key=name, text=name) for name in label_options],
    )

    date_from_field = ft.TextField(label="取込日時 開始（例: 2026-01-01）", width=220)
    date_to_field = ft.TextField(label="取込日時 終了", width=220)
    min_cost_field = ft.TextField(label="total_cost 以上（任意）", width=200)

    refresh_button = ft.Button(content="スキル一覧を更新")
    refresh_button.on_click = refresh_skill_list

    progress_bar = ft.ProgressBar(width=420, value=0, visible=False)
    status_text = ft.Text()
    results_column = ft.Column(spacing=2)

    search_button = ft.Button(content="検索")

    def set_busy(busy: bool) -> None:
        search_button.disabled = busy
        progress_bar.visible = busy
        page.update()

    def render_results(rows, breakdown: dict[int, list[tuple[str, int]]]) -> None:
        results_column.controls.clear()

        if not rows:
            results_column.controls.append(ft.Text("該当する結果はありません"))
            page.update()
            return

        header = ft.Row(
            [
                ft.Text("ID", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("防具", width=120, weight=ft.FontWeight.BOLD),
                ft.Text("スキル", width=240, weight=ft.FontWeight.BOLD),
                ft.Text("合計値", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("total_cost", width=100, weight=ft.FontWeight.BOLD),
                ft.Text("バッチ", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("取込日時", width=160, weight=ft.FontWeight.BOLD),
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
                        ft.Text(row.label or "", width=120),
                        ft.Text(skills_text, width=240),
                        ft.Text(str(row.skill_sum), width=60),
                        ft.Text(str(row.total_cost), width=100),
                        ft.Text(str(row.batch_id), width=60),
                        ft.Text(row.imported_at, width=160),
                    ]
                )
            )
        page.update()

    def run_search() -> None:
        selected_names = [name for name, checkbox in skill_checkboxes.items() if checkbox.value]
        if not selected_names:
            status_text.value = "許可するスキルを1つ以上選択してください"
            page.update()
            return

        min_total_cost: int | None = None
        if min_cost_field.value:
            try:
                min_total_cost = int(min_cost_field.value)
            except ValueError:
                status_text.value = "total_costは数値で入力してください"
                page.update()
                return

        set_busy(True)
        status_text.value = "検索中..."
        page.update()

        conn = get_connection(db_path)
        try:
            registry = SkillRegistry(conn)
            allowed_ids = registry.get_ids(selected_names)
            params = SearchParams(
                allowed_skill_ids=allowed_ids,
                date_from=(date_from_field.value or None),
                date_to=(date_to_field.value or None),
                batch_id=int(batch_dropdown.value) if batch_dropdown.value else None,
                label=(label_dropdown.value or None),
                min_total_cost=min_total_cost,
            )
            rows = search_results(conn, params)
            breakdown = fetch_skill_breakdown(conn, [r.id for r in rows])
        finally:
            conn.close()

        status_text.value = f"検索完了: {len(rows)}件（最大200件まで表示）"
        page.update()
        render_results(rows, breakdown)
        set_busy(False)

    def on_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_search)

    search_button.on_click = on_click

    return ft.Column(
        [
            ft.Text("錬成結果の検索", size=20, weight=ft.FontWeight.BOLD),
            ft.Row([ft.Text("許可するスキル（この中のスキルのみで構成される結果を検索）"), refresh_button]),
            skill_list_container,
            ft.Row([date_from_field, date_to_field, min_cost_field]),
            ft.Row([batch_dropdown, label_dropdown]),
            ft.Row([search_button]),
            progress_bar,
            status_text,
            ft.Divider(),
            ft.Container(content=results_column, expand=True),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
