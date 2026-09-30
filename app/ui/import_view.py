import json
from pathlib import Path
from typing import TYPE_CHECKING, Callable

import flet as ft

from app.core.armor_defaults import reset_armor_defaults
from app.core.equipment import CUSTOM_OPTIONS_KEY, DEFAULT_EQUIPMENT_OPTIONS, resolve_ocr_params
from app.core.importer import ImportSummary, import_block
from app.core.settings import get_json_setting, get_setting, set_json_setting, set_setting
from app.db.connection import get_connection
from app.ui.ocr_label_dialog import show_label_dialog

if TYPE_CHECKING:
    from app.ocr.kuijin_ocr import OcrSession

LAST_SELECTION_KEY = "import_label_last_selection"
# 画像から取込（8bit）の設定を防具ごとに記憶する {防具名: {"base_slot", "zenny_step", "minus_skills", "table"}}
OCR_PARAMS_KEY = "ocr_params_by_armor"
LAST_IMAGE_DIR_KEY = "ocr_last_image_dir"
# 対応していない解像度の画像があったとき、取込タブに並べるファイル名の最大数
_MAX_LISTED_FILES = 50

_PRESET_COLORS = [ft.Colors.RED_200, ft.Colors.BLUE_200, ft.Colors.GREEN_200]
_CUSTOM_COLOR = ft.Colors.AMBER_100
_OPTIONS_PER_ROW = 4


def build_import_view(
    page: ft.Page,
    db_path: Path,
    on_imported: Callable[[int], None] | None = None,
    on_show_results: Callable[[int, str | None], None] | None = None,
) -> ft.Control:
    """取込画面を構築する。

    on_importedは取込成功時（バッチID付き）に呼ばれ、他タブの一覧更新に使う。
    on_show_resultsは「結果を表示しますか」の確認で「はい」を選んだ時に
    バッチID・防具名を渡して呼ばれ、検索タブへの遷移（防具ごとの初期設定の
    適用）に使う。
    """
    progress_bar = ft.ProgressBar(width=400, value=0, visible=False)
    status_text = ft.Text()

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
            # 削除した防具に対する検索初期設定（設定タブ）が孤立して残らないようにする
            reset_armor_defaults(conn, name)
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
        if label_radio_group.value is not None:
            persist_last_selection(label_radio_group.value)
            load_ocr_params(label_radio_group.value)
            page.update()

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

    # --- 画像から取込（8bit）の入力欄 ---
    base_slot_field = ft.TextField(
        label="初期スロット",
        width=120,
        keyboard_type=ft.KeyboardType.NUMBER,
        tooltip="練成前の防具のスロット数（例: 6）",
    )
    zenny_step_dropdown = ft.Dropdown(
        label="1回のゼニー",
        width=140,
        options=[ft.DropdownOption(key="4000", text="4000"), ft.DropdownOption(key="6000", text="6000")],
        value="4000",
    )
    table_dropdown = ft.Dropdown(
        label="抽選テーブル",
        width=150,
        options=[
            ft.DropdownOption(key="5", text="5"),
            ft.DropdownOption(key="6", text="6"),
            ft.DropdownOption(key="none", text="なし（不明）"),
        ],
        tooltip="傀異錬成の抽選テーブル。取込時の仕様チェックに使う（なしの場合はチェックしない）",
    )
    minus_skills_field = ft.TextField(
        label="防具が元から持つスキル",
        hint_text="攻撃:2,火事場力:3",
        width=320,
        tooltip=(
            "「スキル名:元のLv」をカンマ区切りで。これ以外のスキルが下がっていたら読み取りの矛盾として記録します。"
            "スキルが4つ以上あり4つ目以降が画像に写っていないときに、写っていないスキルがマイナスかどうかの判定にも使います"
        ),
    )
    image_dir_text = ft.Text("フォルダ未選択", italic=True)
    selected_image_dir: list[str | None] = [None]

    def load_ocr_params(label: str) -> None:
        conn = get_connection(db_path)
        try:
            raw = get_setting(conn, OCR_PARAMS_KEY)
        finally:
            conn.close()
        saved = json.loads(raw) if raw else {}
        params = resolve_ocr_params(saved, label)
        base_slot_field.value = params["base_slot"]
        zenny_step_dropdown.value = params["zenny_step"]
        minus_skills_field.value = params["minus_skills"]
        table_dropdown.value = params["table"] or "none"

    def save_ocr_params(label: str) -> None:
        conn = get_connection(db_path)
        try:
            raw = get_setting(conn, OCR_PARAMS_KEY)
            saved = json.loads(raw) if raw else {}
            saved[label] = {
                "base_slot": (base_slot_field.value or "").strip(),
                "zenny_step": zenny_step_dropdown.value or "4000",
                "minus_skills": (minus_skills_field.value or "").strip(),
                "table": "" if table_dropdown.value in (None, "none") else table_dropdown.value,
            }
            set_setting(conn, OCR_PARAMS_KEY, json.dumps(saved, ensure_ascii=False))
            if selected_image_dir[0]:
                set_setting(conn, LAST_IMAGE_DIR_KEY, str(Path(selected_image_dir[0]).parent))
        finally:
            conn.close()

    load_ocr_params(last_selection)

    def set_busy(busy: bool) -> None:
        clipboard_import_button.disabled = busy
        image_import_button.disabled = busy
        select_dir_button.disabled = busy
        progress_bar.visible = busy
        page.update()

    def report_progress(done: int, total: int) -> None:
        progress_bar.value = done / total if total else 1
        status_text.value = f"取込中... {done}/{total}"
        page.update()

    def ask_show_results(batch_id: int, label: str | None) -> None:
        """取込完了後に表示し、「はい」ならon_show_resultsで検索タブへ遷移する。"""

        def on_yes(e: ft.Event[ft.Button]) -> None:
            page.pop_dialog()
            if on_show_results is not None:
                on_show_results(batch_id, label)

        def on_no(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("結果を表示しますか"),
            content=ft.Text("取り込んだバッチを対象に、検索タブで結果を表示します。"),
            actions=[
                ft.TextButton(content="いいえ", on_click=on_no),
                ft.Button(content="はい", on_click=on_yes),
            ],
        )
        page.show_dialog(dialog)

    def finish_import(summary: ImportSummary, label: str | None, extra_lines: list[str]) -> None:
        """取込結果を表示し、他タブの一覧更新と「結果を表示しますか」の確認を行う（nx / 8bit 共通）。"""
        status_text.value = (
            f"取込完了: 成功 {summary.imported_count}件 / エラー {summary.error_count}件"
            f"（読込失敗 {len(summary.errors)}件・欠番 {len(summary.skipped_results)}件"
            + "".join(f"・{line}" for line in extra_lines)
            + f"） / 重複除外 {summary.dropped_duplicate_count}件"
            f"（バッチID: {summary.batch_id}）"
        )
        status_text.value += "\n詳細は履歴タブの「エラー」欄から確認できます。"
        if summary.errors:
            preview = "、".join(f"{ln}行目: {msg}" for ln, msg in summary.errors[:5])
            status_text.value += f"\nエラー例: {preview}"

        set_busy(False)

        if summary.imported_count > 0:
            if on_imported is not None:
                on_imported(summary.batch_id)  # 検索/履歴タブのバッチ一覧を最新化する
            if on_show_results is not None:
                ask_show_results(summary.batch_id, label)

    def do_import(text: str) -> None:
        """result_logのテキストを取り込む実処理。呼び出し元（入力欄／クリップボード）を問わない。"""
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

        finish_import(summary, label, [])

    async def on_clipboard_click(e: ft.Event[ft.Button]) -> None:
        text = await ft.Clipboard().get()
        if not text or not text.strip():
            status_text.value = "クリップボードに読み取れるデータがありません"
            page.update()
            return
        page.run_thread(do_import, text)

    clipboard_import_button = ft.Button(content="クリップボードから取込")
    clipboard_import_button.on_click = on_clipboard_click

    async def on_select_dir_click(e: ft.Event[ft.Button]) -> None:
        conn = get_connection(db_path)
        try:
            initial = get_setting(conn, LAST_IMAGE_DIR_KEY)
        finally:
            conn.close()
        path = await ft.FilePicker().get_directory_path(
            dialog_title="練成画像のフォルダを選択", initial_directory=initial
        )
        if path:
            selected_image_dir[0] = path
            count = len(list(Path(path).glob("*.jpg")))
            image_dir_text.value = f"{path}（画像 {count} 枚）"
            image_dir_text.italic = False
            page.update()

    def image_progress(phase: str, done: int, total: int) -> None:
        progress_bar.value = done / total if total else 1
        if phase == "ocr":
            status_text.value = f"画像を読み取り中... {done}/{total}枚"
        else:
            status_text.value = f"取込中... {done}/{total}"
        page.update()

    def do_image_import(
        image_dir: str,
        base_slot: int,
        zenny_step: int,
        minus_skills: dict[str, int] | None,
        table: int | None,
    ) -> None:
        """画像の切り出しと見本との照合。確定していない見本があればラベル入力のダイアログを出す。"""
        # 画像読み取りの依存（numpy / OpenCV）は重いので、使うときだけ読み込む
        from app.ocr.image_import import NoImagesError, start_image_reading
        from app.ocr.kuijin_ocr import UnsupportedResolutionError

        label = label_radio_group.value or None
        set_busy(True)
        progress_bar.value = 0
        status_text.value = "画像の読み取りを開始しました..."
        page.update()

        try:
            session = start_image_reading(
                Path(image_dir), db_path.parent, base_slot, zenny_step, minus_skills, image_progress, table
            )
        except NoImagesError as exc:
            status_text.value = str(exc)
            set_busy(False)
            return
        except UnsupportedResolutionError as exc:
            # 1 枚でもあれば取込は行わない（DB にも見本にも何も保存しない）。該当する画像をすべて示す
            shown = exc.files[:_MAX_LISTED_FILES]
            status_text.value = (
                f"{exc}\n該当する画像をフォルダから除いてから、もう一度取り込んでください。\n"
                + "\n".join(f"・{Path(path).name}（{size}）" for path, size in shown)
                + (f"\n…ほか {len(exc.files) - len(shown)} 枚" if len(exc.files) > len(shown) else "")
            )
            set_busy(False)
            return
        except Exception as exc:  # 読み取り中の想定外のエラーでも画面を固めない
            status_text.value = f"画像の読み取りに失敗しました: {exc}"
            set_busy(False)
            raise

        pending = session.pending_labels()
        if not pending:
            finish_image_import_with(session, label, {})
            return

        def on_labels(labels: dict[tuple[str, int], str] | None) -> None:
            if labels is None:
                status_text.value = "取込を中止しました（新しい見本は保存していません）"
                set_busy(False)
                return
            page.run_thread(finish_image_import_with, session, label, labels)

        status_text.value = f"新しい見本が {len(pending)}個 あります。正しいラベルを選んでください。"
        page.update()
        show_label_dialog(page, pending, base_slot, on_labels)

    def finish_image_import_with(session: "OcrSession", label: str | None, labels: dict[tuple[str, int], str]) -> None:
        """入力されたラベルで読み取り結果を作り、取込元 8bit のバッチとして保存する。"""
        from app.ocr.image_import import finish_image_import

        status_text.value = "読み取り結果を作成中..."
        page.update()
        conn = get_connection(db_path)
        try:
            result = finish_image_import(conn, session, label, labels, image_progress)
        except Exception as exc:
            status_text.value = f"画像からの取込に失敗しました: {exc}"
            set_busy(False)
            raise
        finally:
            conn.close()

        run = result.run
        extra = [f"読み取りの矛盾 {len(run.report.errors)}件", f"仕様違反 {len(run.report.spec_errors)}件"]
        finish_import(result.summary, label, extra)
        status_text.value += (
            f"\n画像 {result.image_count}枚 / 結果画面 {sum(run.screen_counts.values())}枚"
            f"（うちスキルが4つ以上で4つ目以降が写っていないもの {run.screen_counts.get('screen2', 0)}枚）"
            f" / 結果画面以外 {run.not_result_count}枚 / 読込失敗 {run.read_error_count}枚"
            f" / 読み取り {run.timings['total']:.0f}秒"
        )
        if labels:
            status_text.value += f"\n新しい見本 {len(labels)}個 にラベルを付けました。"
        if run.unlabeled:
            status_text.value += (
                "\nラベルが確定していない見本があります（該当する値は「?」になり、読み込めない行になります。"
                "次回の画像取込で再度確認します）: "
                + "、".join(f"{name} {n}個" for name, n in run.unlabeled.items())
            )
        page.update()

    def on_image_import_click(e: ft.Event[ft.Button]) -> None:
        image_dir = selected_image_dir[0]
        if not image_dir:
            status_text.value = "画像のフォルダを選択してください"
            page.update()
            return
        try:
            base_slot = int((base_slot_field.value or "").strip())
        except ValueError:
            status_text.value = "初期スロットを数字で入力してください"
            page.update()
            return
        from app.ocr.kuijin_ocr import parse_minus_skills

        try:
            minus_skills = parse_minus_skills(minus_skills_field.value or "")
        except ValueError:
            status_text.value = "防具が元から持つスキルは「スキル名:元のLv」をカンマで区切って入力してください（例: 攻撃:2,火事場力:3）"
            page.update()
            return
        if label_radio_group.value:
            save_ocr_params(label_radio_group.value)
        page.run_thread(
            do_image_import,
            image_dir,
            base_slot,
            int(zenny_step_dropdown.value or "4000"),
            minus_skills,
            None if table_dropdown.value in (None, "none") else int(table_dropdown.value),
        )

    select_dir_button = ft.Button(content="フォルダを選択", icon=ft.Icons.FOLDER_OPEN)
    select_dir_button.on_click = on_select_dir_click
    image_import_button = ft.Button(content="画像から取込")
    image_import_button.on_click = on_image_import_click

    return ft.Column(
        [
            ft.Text("錬成結果の取込", size=20, weight=ft.FontWeight.BOLD),
            ft.Text("練成している防具", size=16, weight=ft.FontWeight.BOLD),
            label_radio_group,
            ft.Divider(),
            ft.Text("NX Macro Controller の result_log から取込（nx）", size=16, weight=ft.FontWeight.BOLD),
            ft.Row([clipboard_import_button]),
            ft.Divider(),
            ft.Text("練成画像から取込（8bit）", size=16, weight=ft.FontWeight.BOLD),
            ft.Text(
                "Switch で撮った「傀異強化結果」画面のスクリーンショット（*.jpg）を、"
                "1回の連続した記録ごとに1つのフォルダに入れて選択してください。",
            ),
            ft.Row([base_slot_field, zenny_step_dropdown, table_dropdown, minus_skills_field], wrap=True),
            ft.Row([select_dir_button, image_dir_text]),
            ft.Row([image_import_button]),
            progress_bar,
            status_text,
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
