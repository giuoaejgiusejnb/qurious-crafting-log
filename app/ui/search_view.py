from pathlib import Path
from typing import Callable

import flet as ft

from app.core.search import SearchParams, fetch_distinct_labels, fetch_skill_breakdown, search_results
from app.core.skill_master import ALL_MASTER_SKILL_NAMES, SKILL_MASTER
from app.core.skill_registry import SkillRegistry
from app.core.skill_sets import delete_skill_set, get_skill_set, list_skill_set_names, save_skill_set
from app.db.connection import get_connection

_SKILLS_PER_ROW = 5
_SUMMARY_CHIPS_PER_ROW = 8
_UNSELECTED = "__unselected__"


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


def build_search_view(page: ft.Page, db_path: Path) -> tuple[ft.Control, Callable[[], None]]:
    """検索画面を構築する。戻り値は (画面コントロール, バッチ/防具選択肢を最新化する関数)。"""
    skill_checkboxes: dict[str, ft.Checkbox] = {}
    selected_summary_container = ft.Container()
    current_skill_set_name: str | None = None
    current_set_name_text = ft.Text("未選択", weight=ft.FontWeight.BOLD)

    def refresh_current_set_label() -> None:
        if current_skill_set_name:
            current_set_name_text.value = current_skill_set_name
        elif any(checkbox.value for checkbox in skill_checkboxes.values()):
            current_set_name_text.value = "（未保存の選択）"
        else:
            current_set_name_text.value = "未選択"

    def update_selected_summary() -> None:
        selected = [name for name, checkbox in skill_checkboxes.items() if checkbox.value]
        if not selected:
            selected_summary_container.content = ft.Text("スキル未選択", italic=True)
            return

        chips = [
            ft.Container(
                content=ft.Text(name, size=13),
                bgcolor=ft.Colors.BLUE_100,
                border_radius=8,
                padding=ft.Padding.symmetric(horizontal=8, vertical=3),
            )
            for name in selected
        ]
        rows: list[ft.Control] = [
            ft.Row(chips[i : i + _SUMMARY_CHIPS_PER_ROW], spacing=6)
            for i in range(0, len(chips), _SUMMARY_CHIPS_PER_ROW)
        ]
        selected_summary_container.content = ft.Column(rows, spacing=4)

    def on_skill_checkbox_change(e: ft.Event[ft.Checkbox]) -> None:
        nonlocal current_skill_set_name
        current_skill_set_name = None  # 手動変更したので保存済み集合との対応は外れる
        update_selected_summary()
        refresh_current_set_label()
        page.update()

    def build_checkbox_rows(names: list[str], previously_selected: set[str]) -> ft.Control:
        controls: list[ft.Control] = []
        for name in names:
            checkbox = ft.Checkbox(label=name, value=name in previously_selected)
            checkbox.on_change = on_skill_checkbox_change
            skill_checkboxes[name] = checkbox
            controls.append(checkbox)
        rows: list[ft.Control] = [
            ft.Row(controls[i : i + _SKILLS_PER_ROW], spacing=6)
            for i in range(0, len(controls), _SKILLS_PER_ROW)
        ]
        return ft.Column(rows, spacing=2)

    def build_skill_checklist() -> ft.Control:
        # 再構築のたびにチェックボックスは作り直すが、既存の選択状態は引き継ぐ
        previously_selected = {name for name, checkbox in skill_checkboxes.items() if checkbox.value}
        skill_checkboxes.clear()
        sections: list[ft.Control] = []

        for cost, names in SKILL_MASTER:
            sections.append(ft.Text(f"コスト{cost}", weight=ft.FontWeight.BOLD))
            sections.append(build_checkbox_rows(names, previously_selected))

        registered_names = set(_load_skill_names(db_path))
        extra_names = sorted(registered_names - ALL_MASTER_SKILL_NAMES)
        if extra_names:
            sections.append(ft.Text("その他（マスター未登録）", weight=ft.FontWeight.BOLD))
            sections.append(build_checkbox_rows(extra_names, previously_selected))

        return ft.Column(sections, spacing=8)

    def do_clear_selection() -> None:
        nonlocal current_skill_set_name
        for checkbox in skill_checkboxes.values():
            checkbox.value = False
        current_skill_set_name = None
        update_selected_summary()
        refresh_current_set_label()

    def clear_skill_selection(e: ft.Event[ft.TextButton]) -> None:
        do_clear_selection()
        page.update()

    def close_skill_dialog(e: ft.Event[ft.Button]) -> None:
        page.pop_dialog()

    save_set_name_field = ft.TextField(label="スキル集合の名前", width=260)
    save_set_status_text = ft.Text(size=12)

    def do_save_skill_set(name: str, selected_names: list[str]) -> None:
        nonlocal current_skill_set_name
        conn = get_connection(db_path)
        try:
            save_skill_set(conn, name, selected_names)
        finally:
            conn.close()

        current_skill_set_name = name
        refresh_current_set_label()
        refresh_saved_sets_list()
        save_set_status_text.value = f"「{name}」として保存しました"
        save_set_name_field.value = ""
        page.update()

    def show_overwrite_confirm(name: str, selected_names: list[str]) -> None:
        def on_confirm(e: ft.Event[ft.Button]) -> None:
            page.pop_dialog()  # 確認ダイアログを閉じる
            do_save_skill_set(name, selected_names)

        def on_cancel(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("上書きの確認"),
            content=ft.Text(f"「{name}」は既に存在します。上書きしますか？"),
            actions=[
                ft.TextButton(content="キャンセル", on_click=on_cancel),
                ft.Button(content="上書きする", on_click=on_confirm),
            ],
        )
        page.show_dialog(confirm_dialog)

    def save_current_skill_set(e: ft.Event[ft.Button]) -> None:
        name = (save_set_name_field.value or "").strip()
        selected_names = [n for n, checkbox in skill_checkboxes.items() if checkbox.value]

        if not name:
            save_set_status_text.value = "名前を入力してください"
            page.update()
            return
        if not selected_names:
            save_set_status_text.value = "スキルを1つ以上選択してください"
            page.update()
            return

        conn = get_connection(db_path)
        try:
            existing = get_skill_set(conn, name)
        finally:
            conn.close()

        if existing is not None:
            show_overwrite_confirm(name, selected_names)
        else:
            do_save_skill_set(name, selected_names)

    save_set_button = ft.Button(content="この内容を保存")
    save_set_button.on_click = save_current_skill_set

    def build_dialog_content() -> ft.Control:
        return ft.Column(
            [
                ft.Text("保存済みのスキル集合", weight=ft.FontWeight.BOLD),
                saved_sets_list_container,
                ft.Divider(),
                ft.Text("選択中のスキル", weight=ft.FontWeight.BOLD),
                selected_summary_container,
                ft.Row([save_set_name_field, save_set_button]),
                save_set_status_text,
                ft.Divider(),
                build_skill_checklist(),
            ],
            width=760,
            scroll=ft.ScrollMode.AUTO,
            height=650,
        )

    def open_skill_dialog(e: ft.Event[ft.Button]) -> None:
        # 開くたびに新しいAlertDialogインスタンスを作る
        # （既存インスタンスのcontentを差し替える方式だと、再表示時にクライアント側の
        #   描画とサーバー側の状態がずれてチェック状態を正しく拾えないことがあるため）
        save_set_status_text.value = ""
        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("検索するスキル集合を選択"),
            content=build_dialog_content(),
            actions=[
                ft.TextButton(content="選択をクリア", on_click=clear_skill_selection),
                ft.Button(content="閉じる", on_click=close_skill_dialog),
            ],
        )
        page.show_dialog(dialog)

    select_skill_button = ft.Button(content="スキル集合を作成")
    select_skill_button.on_click = open_skill_dialog

    def open_current_selection_detail(e: ft.Event[ft.IconButton]) -> None:
        selected = [name for name, checkbox in skill_checkboxes.items() if checkbox.value]

        def close_detail(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(current_skill_set_name or "現在選択中のスキル"),
            content=ft.Text("、".join(selected) if selected else "（スキルが選択されていません）"),
            actions=[ft.TextButton(content="閉じる", on_click=close_detail)],
        )
        page.show_dialog(dialog)

    current_set_detail_button = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE, tooltip="現在の選択内容を見る", on_click=open_current_selection_detail
    )

    def clear_current_selection_from_main(e: ft.Event[ft.IconButton]) -> None:
        do_clear_selection()
        page.update()

    clear_current_selection_button = ft.IconButton(
        icon=ft.Icons.CLOSE, tooltip="未選択に戻す", on_click=clear_current_selection_from_main
    )

    def apply_named_skill_set(name: str) -> None:
        nonlocal current_skill_set_name
        conn = get_connection(db_path)
        try:
            names = get_skill_set(conn, name) or []
        finally:
            conn.close()

        names_set = set(names)
        for skill_name, checkbox in skill_checkboxes.items():
            checkbox.value = skill_name in names_set
        current_skill_set_name = name
        update_selected_summary()
        refresh_current_set_label()
        save_set_status_text.value = f"「{name}」を選択中のスキルに反映しました"
        page.update()

    def open_skill_set_detail(name: str) -> None:
        conn = get_connection(db_path)
        try:
            names = get_skill_set(conn, name) or []
        finally:
            conn.close()

        def use_this_set(e: ft.Event[ft.Button]) -> None:
            page.pop_dialog()
            apply_named_skill_set(name)

        def close_detail(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        detail_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"「{name}」の内容"),
            content=ft.Text("、".join(names) if names else "（スキルが登録されていません）"),
            actions=[
                ft.TextButton(content="閉じる", on_click=close_detail),
                ft.Button(content="このスキル集合を使う", on_click=use_this_set),
            ],
        )
        page.show_dialog(detail_dialog)

    def confirm_delete_skill_set(name: str) -> None:
        def do_delete(e: ft.Event[ft.Button]) -> None:
            nonlocal current_skill_set_name
            conn = get_connection(db_path)
            try:
                delete_skill_set(conn, name)
            finally:
                conn.close()
            if current_skill_set_name == name:
                current_skill_set_name = None
                refresh_current_set_label()
            page.pop_dialog()
            refresh_saved_sets_list()
            save_set_status_text.value = f"「{name}」を削除しました"
            page.update()

        def cancel_delete(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("削除の確認"),
            content=ft.Text(f"「{name}」を削除しますか？この操作は取り消せません。"),
            actions=[
                ft.TextButton(content="キャンセル", on_click=cancel_delete),
                ft.Button(content="削除する", on_click=do_delete),
            ],
        )
        page.show_dialog(confirm_dialog)

    def build_saved_sets_list() -> ft.Control:
        conn = get_connection(db_path)
        try:
            names = list_skill_set_names(conn)
        finally:
            conn.close()

        if not names:
            return ft.Text("保存済みのスキル集合はまだありません", italic=True)

        rows: list[ft.Control] = []
        for name in names:
            rows.append(
                ft.Row(
                    [
                        ft.TextButton(
                            content=name,
                            on_click=lambda e, n=name: apply_named_skill_set(n),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.INFO_OUTLINE,
                            tooltip="詳細を見る",
                            on_click=lambda e, n=name: open_skill_set_detail(n),
                        ),
                        ft.IconButton(
                            icon=ft.Icons.DELETE,
                            tooltip="削除",
                            icon_color=ft.Colors.RED_400,
                            on_click=lambda e, n=name: confirm_delete_skill_set(n),
                        ),
                    ],
                    spacing=0,
                )
            )
        return ft.Column(rows, spacing=0)

    saved_sets_list_container = ft.Container()

    def refresh_saved_sets_list() -> None:
        saved_sets_list_container.content = build_saved_sets_list()

    refresh_saved_sets_list()

    update_selected_summary()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    batch_dropdown = ft.Dropdown(
        label="対象バッチ（未選択なら全体）",
        width=420,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    label_dropdown = ft.Dropdown(
        label="防具（未選択なら全体）",
        width=220,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    def _load_filter_data() -> None:
        batch_options = _load_batch_options(db_path)
        batch_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=str(bid), text=text) for bid, text in batch_options],
        ]
        if batch_dropdown.value not in {opt.key for opt in batch_dropdown.options}:
            batch_dropdown.value = _UNSELECTED

        label_options = _load_label_options(db_path)
        label_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=name, text=name) for name in label_options],
        ]
        if label_dropdown.value not in {opt.key for opt in label_dropdown.options}:
            label_dropdown.value = _UNSELECTED

    def refresh_filter_options() -> None:
        """取込タブでの取込完了時に外部から呼ばれ、バッチ/防具の選択肢を最新化する。

        ページ接続後にのみ呼ばれる想定（page.update()を呼ぶため）。
        """
        _load_filter_data()
        page.update()

    _load_filter_data()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    threshold_dropdown = ft.Dropdown(
        label="必要な個数（1〜4）",
        width=160,
        value="2",
        options=[ft.DropdownOption(key=str(n), text=str(n)) for n in (1, 2, 3, 4)],
    )

    date_from_field = ft.TextField(label="取込日時 開始（例: 2026-01-01）", width=220)
    date_to_field = ft.TextField(label="取込日時 終了", width=220)
    min_cost_field = ft.TextField(label="total_cost 以上（任意）", width=200)

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
                ft.Text("スキル欠け", width=80, weight=ft.FontWeight.BOLD),
                ft.Text("total_cost", width=100, weight=ft.FontWeight.BOLD),
                ft.Text("バッチ", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("取込日時", width=160, weight=ft.FontWeight.BOLD),
            ]
        )
        results_column.controls.append(header)
        results_column.controls.append(ft.Divider(height=1))

        for row in rows:
            skills_text = "、".join(f"{name}{value:+d}" for name, value in breakdown.get(row.id, []))
            results_column.controls.append(
                ft.Row(
                    [
                        ft.Text(str(row.id), width=60),
                        ft.Text(row.label or "", width=120),
                        ft.Text(skills_text, width=240),
                        ft.Text(str(row.skill_sum), width=60),
                        ft.Text("有" if row.has_deficiency else "無", width=80),
                        ft.Text(str(row.total_cost), width=100),
                        ft.Text(str(row.batch_id), width=60),
                        ft.Text(row.imported_at, width=160),
                    ]
                )
            )
        page.update()

    def run_search() -> None:
        # スキル未選択でもよい（他の条件のみで検索する）
        selected_names = [name for name, checkbox in skill_checkboxes.items() if checkbox.value]

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
                threshold=int(threshold_dropdown.value or 1),
                date_from=(date_from_field.value or None),
                date_to=(date_to_field.value or None),
                batch_id=(
                    int(batch_dropdown.value)
                    if batch_dropdown.value and batch_dropdown.value != _UNSELECTED
                    else None
                ),
                label=(
                    label_dropdown.value
                    if label_dropdown.value and label_dropdown.value != _UNSELECTED
                    else None
                ),
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

    view = ft.Column(
        [
            ft.Text("錬成結果の検索", size=20, weight=ft.FontWeight.BOLD),
            ft.Text(
                "選択したスキルの合計値（＋2は同じスキル2個分）が下の個数以上の結果を検索します。"
                "集合外のスキルを含んでいても除外されません。"
            ),
            ft.Row(
                [
                    select_skill_button,
                    current_set_name_text,
                    current_set_detail_button,
                    clear_current_selection_button,
                    threshold_dropdown,
                ]
            ),
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
    return view, refresh_filter_options
