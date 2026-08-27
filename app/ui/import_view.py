from pathlib import Path
from typing import Callable

import flet as ft

from app.core.importer import import_block
from app.core.settings import get_json_setting, get_setting, set_json_setting, set_setting
from app.db.connection import get_connection

DEFAULT_EQUIPMENT_OPTIONS = ["ギルパレ脚", "クシャ胴", "マッスル腕"]
LAST_SELECTION_KEY = "import_label_last_selection"
CUSTOM_OPTIONS_KEY = "import_label_custom_options"

_PRESET_COLORS = [ft.Colors.RED_200, ft.Colors.BLUE_200, ft.Colors.GREEN_200]
_CUSTOM_COLOR = ft.Colors.AMBER_100
_OPTIONS_PER_ROW = 4


def build_import_view(
    page: ft.Page,
    db_path: Path,
    on_imported: Callable[[], None] | None = None,
) -> ft.Control:
    """取込画面を構築する。on_importedは取込成功時に呼ばれ、他タブの一覧更新に使う。"""
    log_field = ft.TextField(
        label="result_log（複数行貼り付け可）",
        multiline=True,
        min_lines=10,
        max_lines=16,
        expand=True,
    )
    progress_bar = ft.ProgressBar(width=400, value=0, visible=False)
    status_text = ft.Text()
    import_button = ft.Button(content="取込")

    # --- 練成している防具 選択UI ---
    setting_conn = get_connection(db_path)
    try:
        custom_options = get_json_setting(setting_conn, CUSTOM_OPTIONS_KEY, [])
        last_selection = get_setting(setting_conn, LAST_SELECTION_KEY) or DEFAULT_EQUIPMENT_OPTIONS[0]
    finally:
        setting_conn.close()

    all_options = list(DEFAULT_EQUIPMENT_OPTIONS)
    for opt in custom_options:
        if opt not in all_options:
            all_options.append(opt)
    if last_selection not in all_options:
        all_options.append(last_selection)

    options_container = ft.Container()

    def persist_last_selection(value: str) -> None:
        conn = get_connection(db_path)
        try:
            set_setting(conn, LAST_SELECTION_KEY, value)
        finally:
            conn.close()

    def delete_custom_option(name: str) -> None:
        if name not in all_options or name in DEFAULT_EQUIPMENT_OPTIONS:
            return

        all_options.remove(name)
        custom_only = [o for o in all_options if o not in DEFAULT_EQUIPMENT_OPTIONS]
        conn = get_connection(db_path)
        try:
            set_json_setting(conn, CUSTOM_OPTIONS_KEY, custom_only)
        finally:
            conn.close()

        if label_radio_group.value == name:
            label_radio_group.value = DEFAULT_EQUIPMENT_OPTIONS[0]
            persist_last_selection(label_radio_group.value)

        refresh_options_layout()
        page.update()

    def build_option_control(opt: str) -> ft.Control:
        radio = ft.Radio(
            value=opt,
            label=opt,
            label_style=ft.TextStyle(size=16, weight=ft.FontWeight.BOLD),
        )
        if opt in DEFAULT_EQUIPMENT_OPTIONS:
            color = _PRESET_COLORS[DEFAULT_EQUIPMENT_OPTIONS.index(opt) % len(_PRESET_COLORS)]
            return ft.Container(
                content=radio,
                bgcolor=color,
                border_radius=10,
                padding=ft.Padding.symmetric(horizontal=12, vertical=2),
            )
        return ft.Container(
            content=ft.Row(
                [
                    radio,
                    ft.IconButton(
                        icon=ft.Icons.CLOSE,
                        icon_size=16,
                        tooltip=f"{opt}を削除",
                        on_click=lambda e, name=opt: delete_custom_option(name),
                    ),
                ],
                spacing=0,
            ),
            bgcolor=_CUSTOM_COLOR,
            border_radius=10,
            padding=ft.Padding.symmetric(horizontal=8, vertical=2),
        )

    def build_options_layout() -> ft.Control:
        controls = [build_option_control(opt) for opt in all_options] + [add_option_button]
        rows: list[ft.Control] = [
            ft.Row(controls[i : i + _OPTIONS_PER_ROW], spacing=10)
            for i in range(0, len(controls), _OPTIONS_PER_ROW)
        ]
        return ft.Column(rows, spacing=10)

    def refresh_options_layout() -> None:
        options_container.content = build_options_layout()

    def on_selection_change(e: ft.Event[ft.RadioGroup]) -> None:
        persist_last_selection(label_radio_group.value)

    label_radio_group = ft.RadioGroup(value=last_selection, content=options_container)
    label_radio_group.on_change = on_selection_change

    new_option_field = ft.TextField(label="装備名", autofocus=True)

    def close_add_dialog(e: ft.Event[ft.TextButton] | None = None) -> None:
        page.pop_dialog()

    def confirm_add_option(e: ft.Event[ft.Button]) -> None:
        name = (new_option_field.value or "").strip()
        new_option_field.value = ""
        if not name:
            page.pop_dialog()
            return

        if name not in all_options:
            all_options.append(name)
            custom_only = [o for o in all_options if o not in DEFAULT_EQUIPMENT_OPTIONS]
            conn = get_connection(db_path)
            try:
                set_json_setting(conn, CUSTOM_OPTIONS_KEY, custom_only)
            finally:
                conn.close()
            refresh_options_layout()

        label_radio_group.value = name
        persist_last_selection(name)
        page.pop_dialog()
        page.update()

    add_dialog = ft.AlertDialog(
        modal=True,
        title=ft.Text("装備を追加"),
        content=new_option_field,
        actions=[
            ft.TextButton(content="キャンセル", on_click=close_add_dialog),
            ft.Button(content="追加", on_click=confirm_add_option),
        ],
    )

    def open_add_dialog(e: ft.Event[ft.IconButton]) -> None:
        new_option_field.value = ""
        page.show_dialog(add_dialog)

    add_option_button = ft.IconButton(icon=ft.Icons.ADD, tooltip="装備を追加", on_click=open_add_dialog)

    refresh_options_layout()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

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
        label = label_radio_group.value or None

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

        if summary.imported_count > 0 and on_imported is not None:
            on_imported()  # 検索/履歴タブのバッチ一覧を最新化する

    def on_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_import)

    import_button.on_click = on_click

    return ft.Column(
        [
            ft.Text("錬成結果の取込", size=20, weight=ft.FontWeight.BOLD),
            log_field,
            ft.Text("練成している防具", size=16, weight=ft.FontWeight.BOLD),
            label_radio_group,
            ft.Row([import_button]),
            progress_bar,
            status_text,
        ],
        expand=True,
    )
