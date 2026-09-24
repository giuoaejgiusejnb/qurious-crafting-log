from pathlib import Path

import flet as ft

from app.core.armor_defaults import list_armors_using_skill_set
from app.core.skill_master import ALL_MASTER_SKILL_NAMES, SKILL_MASTER
from app.core.skill_sets import (
    delete_skill_set,
    get_skill_set,
    list_skill_set_names,
    save_skill_set,
)
from app.db.connection import get_connection

_SKILLS_PER_ROW = 5
_SUMMARY_CHIPS_PER_ROW = 8
_SAVED_SETS_PER_ROW = 3
# 名前が極端に長くても詳細/削除ボタンが画面外に押し出されないよう、
# 名前部分の表示幅を固定し、それより長い名前は省略記号で切り詰める。
_SAVED_SET_NAME_WIDTH = 100

_SCROLL_ANCHOR_KEY = ft.ScrollKey("skill_set_manager_scroll_anchor")


def _load_skill_names(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    try:
        rows = conn.execute("SELECT name FROM skills ORDER BY name").fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


def build_skill_set_manager_content(page: ft.Page, db_path: Path) -> ft.Control:
    """スキル集合の作成・編集・削除を行う画面（設定タブの「スキル集合管理」から使う）。

    検索タブ・防具ごとの検索初期設定の「スキル集合」ドロップダウンは、
    ここで保存された名前を参照するだけで、作成・編集・削除はここに一本化する
    （複数箇所で編集できるようにすると、選択肢一覧の同期漏れなどの不具合が
    増えるため）。
    """
    skill_checkboxes: dict[str, ft.Checkbox] = {}
    selected_summary_container = ft.Container()
    save_set_name_field = ft.TextField(label="スキル集合の名前", width=260)
    save_set_status_text = ft.Text(size=12)
    saved_sets_list_container = ft.Container()
    checklist_container = ft.Container()

    def update_selected_summary() -> None:
        selected = [
            name for name, checkbox in skill_checkboxes.items() if checkbox.value
        ]
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
        update_selected_summary()
        page.update()

    def build_checkbox_rows(
        names: list[str], previously_selected: set[str]
    ) -> ft.Control:
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

    def select_all_in_group(names: list[str]) -> None:
        for name in names:
            skill_checkboxes[name].value = True
        update_selected_summary()
        page.update()

    def clear_all_in_group(names: list[str]) -> None:
        for name in names:
            skill_checkboxes[name].value = False
        update_selected_summary()
        page.update()

    def build_group_header(title: str, names: list[str]) -> ft.Control:
        return ft.Row(
            [
                ft.Text(title, weight=ft.FontWeight.BOLD),
                ft.TextButton(
                    content="すべて選択",
                    on_click=lambda e, ns=names: select_all_in_group(ns),
                ),
                ft.TextButton(
                    content="すべてクリア",
                    on_click=lambda e, ns=names: clear_all_in_group(ns),
                ),
            ]
        )

    def build_skill_checklist() -> ft.Control:
        # 再構築のたびにチェックボックスは作り直すが、既存の選択状態は引き継ぐ
        previously_selected = {
            name for name, checkbox in skill_checkboxes.items() if checkbox.value
        }
        skill_checkboxes.clear()
        sections: list[ft.Control] = []

        for cost, names in SKILL_MASTER:
            sections.append(build_group_header(f"コスト{cost}", names))
            sections.append(build_checkbox_rows(names, previously_selected))

        registered_names = set(_load_skill_names(db_path))
        extra_names = sorted(registered_names - ALL_MASTER_SKILL_NAMES)
        if extra_names:
            sections.append(build_group_header("その他（マスター未登録）", extra_names))
            sections.append(build_checkbox_rows(extra_names, previously_selected))

        return ft.Column(sections, spacing=8)

    def refresh_checklist() -> None:
        checklist_container.content = build_skill_checklist()

    def do_clear_selection() -> None:
        for checkbox in skill_checkboxes.values():
            checkbox.value = False
        update_selected_summary()

    def clear_skill_selection(e: ft.Event[ft.TextButton]) -> None:
        do_clear_selection()
        page.update()

    async def do_scroll_to_top() -> None:
        await content.scroll_to(scroll_key=_SCROLL_ANCHOR_KEY, duration=0)

    def scroll_to_top(e: ft.Event[ft.TextButton]) -> None:
        page.run_task(do_scroll_to_top)

    def do_save_skill_set(name: str, selected_names: list[str]) -> None:
        conn = get_connection(db_path)
        try:
            save_skill_set(conn, name, selected_names)
        finally:
            conn.close()

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
        selected_names = [
            n for n, checkbox in skill_checkboxes.items() if checkbox.value
        ]

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

    def load_named_skill_set_into_checklist(name: str) -> None:
        """「保存済みのスキル集合」一覧の名前クリック時に呼ばれる。

        既存の内容を下敷きにして編集・上書き保存するための読み込み。
        """
        conn = get_connection(db_path)
        try:
            names = get_skill_set(conn, name) or []
        finally:
            conn.close()

        names_set = set(names)
        for skill_name, checkbox in skill_checkboxes.items():
            checkbox.value = skill_name in names_set
        update_selected_summary()
        save_set_status_text.value = f"「{name}」の内容をチェックボックスに読み込みました"
        page.update()

    def open_skill_set_detail(name: str) -> None:
        conn = get_connection(db_path)
        try:
            names = get_skill_set(conn, name) or []
        finally:
            conn.close()

        def close_detail(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        detail_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"「{name}」の内容"),
            content=ft.Text(
                "、".join(names) if names else "（スキルが登録されていません）"
            ),
            actions=[
                ft.TextButton(content="閉じる", on_click=close_detail),
            ],
        )
        page.show_dialog(detail_dialog)

    def confirm_delete_skill_set(name: str) -> None:
        def do_delete(e: ft.Event[ft.Button]) -> None:
            conn = get_connection(db_path)
            try:
                delete_skill_set(conn, name)
            finally:
                conn.close()
            page.pop_dialog()
            refresh_saved_sets_list()
            save_set_status_text.value = f"「{name}」を削除しました"
            page.update()

        def cancel_delete(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        conn = get_connection(db_path)
        try:
            armors_using_it = list_armors_using_skill_set(conn, name)
        finally:
            conn.close()

        message = f"「{name}」を削除しますか？この操作は取り消せません。"
        if armors_using_it:
            armor_list = "、".join(armors_using_it)
            message += (
                f"\n\n⚠ このスキル集合は防具「{armor_list}」の検索初期設定（設定タブ）で"
                "使われています。削除すると、その防具の初期設定はスキル未選択として扱われます。"
            )

        confirm_dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("削除の確認"),
            content=ft.Text(message),
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

        entries: list[ft.Control] = []
        for name in names:
            entries.append(
                ft.Row(
                    [
                        # 名前をクリックすると、その内容をチェックボックスに読み込む
                        # （編集・上書き保存の下書き用）。
                        ft.TextButton(
                            content=ft.Text(
                                name,
                                width=_SAVED_SET_NAME_WIDTH,
                                max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS,
                            ),
                            tooltip=name,  # 省略されても元の名前が分かるように
                            on_click=lambda e, n=name: load_named_skill_set_into_checklist(n),
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
        # wrap=Trueは折り返し判定に親からの幅の伝播が必要で不安定だったため、
        # スキルチェックボックスの並びなどと同じ「固定数ごとに手動で行分割」方式にする。
        rows: list[ft.Control] = [
            ft.Row(entries[i : i + _SAVED_SETS_PER_ROW], spacing=8)
            for i in range(0, len(entries), _SAVED_SETS_PER_ROW)
        ]
        return ft.Column(rows, spacing=4)

    def refresh_saved_sets_list() -> None:
        saved_sets_list_container.content = build_saved_sets_list()

    refresh_saved_sets_list()
    refresh_checklist()
    update_selected_summary()

    content = ft.Column(
        [
            ft.Text(
                "スキル集合管理",
                size=18,
                weight=ft.FontWeight.BOLD,
                key=_SCROLL_ANCHOR_KEY,
            ),
            ft.Text(
                "検索タブ・防具ごとの検索初期設定で使う「スキル集合」を作成・編集・"
                "削除できます。名前をクリックすると内容をチェックボックスに読み込んで"
                "編集できます（上書き保存も新規作成と同じ手順です）。"
            ),
            ft.Text("保存済みのスキル集合", weight=ft.FontWeight.BOLD),
            saved_sets_list_container,
            ft.Divider(),
            ft.Text("選択中のスキル", weight=ft.FontWeight.BOLD),
            selected_summary_container,
            ft.Row([save_set_name_field, save_set_button]),
            ft.Row(
                [
                    ft.TextButton(content="一番上に戻る", on_click=scroll_to_top),
                    ft.TextButton(content="選択をクリア", on_click=clear_skill_selection),
                ]
            ),
            save_set_status_text,
            ft.Divider(),
            checklist_container,
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
        expand=True,
    )
    return content
