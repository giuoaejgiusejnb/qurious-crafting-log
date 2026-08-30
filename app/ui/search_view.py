from collections.abc import Callable
from pathlib import Path

import flet as ft

from app.core.armor_defaults import ArmorSearchDefaults, list_armors_using_skill_set
from app.core.collection import CollectionLimitError, set_collected
from app.core.search import (
    COST_OPTIONS,
    DEFAULT_SORT,
    RESISTANCE_OPTIONS,
    SearchParams,
    fetch_distinct_import_dates,
    fetch_distinct_labels,
    fetch_skill_breakdown,
    search_results,
)
from app.core.skill_master import ALL_MASTER_SKILL_NAMES, SKILL_MASTER
from app.core.skill_registry import SkillRegistry
from app.core.skill_sets import (
    delete_skill_set,
    get_skill_set,
    list_skill_set_names,
    save_skill_set,
)
from app.db.connection import get_connection
from app.ui.skills_display import build_skills_wrap

_SKILLS_PER_ROW = 5
_SUMMARY_CHIPS_PER_ROW = 8
_SAVED_SETS_PER_ROW = 3
# 名前が極端に長くても詳細/削除ボタンが画面外に押し出されないよう、
# 名前部分の表示幅を固定し、それより長い名前は省略記号で切り詰める。
# 1エントリはボタンの内側余白・アイコン2つ分を含めると名前の表示幅より
# だいぶ広くなるため、ダイアログの幅（760px）に収まるよう余裕を持たせている。
_SAVED_SET_NAME_WIDTH = 100
_UNSELECTED = "__unselected__"
_PAGE_SIZE = 200

_DEFAULT_COST_MIN = "3"
_DEFAULT_COST_MAX = "42"

_BATCH_MODE = "batch"
_DATE_RANGE_MODE = "date_range"

# ページ送り後にスクロールで戻る先の目印。今は画面最上部のタイトルに付けているが、
# 例えば「上部の前へ/次へボタンの位置に戻る」等に変更したい場合は、
# このkeyを付け替える対象コントロールを変えるだけでよい。
# 単なる文字列ではなくft.ScrollKeyを使う必要がある
# （通常のkey（ValueKey相当）はスクロール先指定用としては認識されない）。
_SCROLL_ANCHOR_KEY = ft.ScrollKey("search_view_scroll_anchor")


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


def _load_import_date_options(db_path: Path) -> list[str]:
    conn = get_connection(db_path)
    try:
        return fetch_distinct_import_dates(conn)
    finally:
        conn.close()


def build_search_view(
    page: ft.Page,
    db_path: Path,
    on_collected: Callable[[int], None] | None = None,
) -> tuple[ft.Control, Callable[[], None], Callable[[int, ArmorSearchDefaults | None], None]]:
    """検索画面を構築する。

    戻り値は (画面コントロール, バッチ/防具選択肢を最新化する関数,
    指定バッチを対象に検索を実行する関数)。
    最後の関数は取込タブ・履歴タブからの連携に使う。第2引数（防具ごとの
    検索初期設定）を渡すとその内容を復元し（取込タブから遷移時）、
    省略するとすべて既定値にリセットする（履歴タブから遷移時）。
    on_collectedは「回収」にチェックを入れたときにバッチIDを渡して呼ばれ、
    回収確認サイドパネルを自動的に開くのに使う。
    """
    # skill_checkboxesは「検索するスキル集合を作成」ダイアログ内だけで完結する
    # 作業領域（スクラッチパッド）。ここでの操作（チェックの切り替え、一覧からの
    # 読み込みなど）はcurrent_set_dropdownには一切影響しない。検索に実際に使う
    # スキル集合はcurrent_set_dropdownの選択のみで決まり、「保存」または
    # （選択中の集合が）「削除」された場合にのみドロップダウンが変わる。
    skill_checkboxes: dict[str, ft.Checkbox] = {}
    selected_summary_container = ft.Container()
    current_set_dropdown = ft.Dropdown(
        label="使用するスキル集合",
        width=280,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    def refresh_current_set_dropdown() -> None:
        """スキル集合ドロップダウンの選択肢を更新する。

        現在の選択値が引き続き有効（未選択、または存在する保存済み集合名）で
        あればそのまま維持し、そうでなくなっていれば（選択中だった集合が
        削除された場合など）未選択に戻す。他の絞り込み用ドロップダウン
        （バッチ・防具など）と同じ「無効になっていたらリセット」方式。
        """
        conn = get_connection(db_path)
        try:
            saved_names = list_skill_set_names(conn)
        finally:
            conn.close()

        options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=n, text=n) for n in saved_names],
        ]
        current_set_dropdown.options = options
        if current_set_dropdown.value not in {opt.key for opt in options}:
            current_set_dropdown.value = _UNSELECTED

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

    def mark_manual_selection_change() -> None:
        """チェックボックスの状態が変わったときの共通処理（ダイアログ内表示の更新のみ）。"""
        update_selected_summary()

    def on_skill_checkbox_change(e: ft.Event[ft.Checkbox]) -> None:
        mark_manual_selection_change()
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
        mark_manual_selection_change()
        page.update()

    def clear_all_in_group(names: list[str]) -> None:
        for name in names:
            skill_checkboxes[name].value = False
        mark_manual_selection_change()
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

    def do_clear_selection() -> None:
        for checkbox in skill_checkboxes.values():
            checkbox.value = False
        update_selected_summary()

    def clear_skill_selection(e: ft.Event[ft.TextButton]) -> None:
        do_clear_selection()
        page.update()

    def close_skill_dialog(e: ft.Event[ft.Button]) -> None:
        page.pop_dialog()

    save_set_name_field = ft.TextField(label="スキル集合の名前", width=260)
    save_set_status_text = ft.Text(size=12)

    def do_save_skill_set(name: str, selected_names: list[str]) -> None:
        conn = get_connection(db_path)
        try:
            save_skill_set(conn, name, selected_names)
        finally:
            conn.close()

        # 保存してもcurrent_set_dropdownの選択は変えない（ドロップダウンの選択肢
        # 一覧だけは、新しく保存した名前を選べるように更新する）。
        refresh_current_set_dropdown()
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
            title=ft.Text("検索するスキル集合を作成"),
            content=build_dialog_content(),
            actions=[
                ft.TextButton(content="選択をクリア", on_click=clear_skill_selection),
                ft.Button(content="保存せずに閉じる", on_click=close_skill_dialog),
            ],
        )
        page.show_dialog(dialog)

    select_skill_button = ft.Button(content="スキル集合を作成")
    select_skill_button.on_click = open_skill_dialog

    def open_current_selection_detail(e: ft.Event[ft.IconButton]) -> None:
        # 実際に検索で使われるcurrent_set_dropdownの選択内容を表示する
        # （ダイアログ内のチェックボックスの状態ではない）。
        value = current_set_dropdown.value
        if value and value != _UNSELECTED:
            conn = get_connection(db_path)
            try:
                selected = get_skill_set(conn, value) or []
            finally:
                conn.close()
            title = value
        else:
            selected = []
            title = "現在選択中のスキル"

        def close_detail(e: ft.Event[ft.TextButton]) -> None:
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(title),
            content=ft.Text(
                "、".join(selected) if selected else "（スキルが選択されていません）"
            ),
            actions=[ft.TextButton(content="閉じる", on_click=close_detail)],
        )
        page.show_dialog(dialog)

    current_set_detail_button = ft.IconButton(
        icon=ft.Icons.INFO_OUTLINE,
        tooltip="現在の選択内容を見る",
        on_click=open_current_selection_detail,
    )

    def load_named_skill_set_into_checklist(name: str) -> None:
        """「保存済みのスキル集合」一覧の名前クリック時に呼ばれる。

        チェックボックス（ダイアログ内の作業領域）には内容を反映するが、
        current_set_dropdown（実際に検索に使われる値）は一切変更しない。
        既存の内容を下敷きにして編集・上書き保存するための読み込みであり、
        「これを検索に使う」という意思表示ではないため。
        """
        conn = get_connection(db_path)
        try:
            names = get_skill_set(conn, name) or []
        finally:
            conn.close()

        names_set = set(names)
        for skill_name, checkbox in skill_checkboxes.items():
            checkbox.value = skill_name in names_set
        mark_manual_selection_change()
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
            # current_set_dropdownが削除した名前を選択中だった場合のみ、
            # 未選択に戻る（refresh_current_set_dropdown内の「無効なら
            # リセット」ロジックによる。それ以外は変更しない）。
            refresh_current_set_dropdown()
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
                        # （編集・上書き保存の下書き用）。current_set_dropdownは
                        # 直接は変更しないが、チェックボックスの状態が変わるため
                        # 結果的に「（未保存の選択）」表示になる（手動でのチェック
                        # 操作と同じ扱い。検索に使うスキル集合の切り替えは
                        # ドロップダウンでの選択のみ）。
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

    saved_sets_list_container = ft.Container()

    def refresh_saved_sets_list() -> None:
        saved_sets_list_container.content = build_saved_sets_list()

    refresh_saved_sets_list()

    # skill_checkboxesは、従来は「スキル集合を作成」ダイアログを開いたときに
    # build_skill_checklist()経由で初めて作られていた。しかしskill_checkboxesは
    # 検索実行時の選択スキル一覧や「現在の選択内容を見る」ダイアログでも参照するため、
    # ダイアログを一度も開いていない状態（例: スキル集合ドロップダウンで直接選んだ
    # だけの場合）だと選択が空として扱われてしまう不具合があった。ここで一度呼んで
    # 初期化しておく（戻り値のColumnはダイアログ内でのみ使うためここでは捨てる）。
    build_skill_checklist()

    update_selected_summary()  # 初期表示（ページ未接続のためpage.update()は呼ばない）
    refresh_current_set_dropdown()  # 同上

    batch_dropdown = ft.Dropdown(
        label="対象バッチ",
        width=380,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    label_dropdown = ft.Dropdown(
        label="防具（未選択なら全体）",
        width=220,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    date_from_dropdown = ft.Dropdown(
        label="開始日",
        width=180,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    date_to_dropdown = ft.Dropdown(
        label="終了日",
        width=180,
        value=_UNSELECTED,
        options=[ft.DropdownOption(key=_UNSELECTED, text="（未選択）")],
    )

    def _load_filter_data() -> None:
        batch_options = _load_batch_options(db_path)
        batch_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[
                ft.DropdownOption(key=str(bid), text=text)
                for bid, text in batch_options
            ],
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

        date_options = _load_import_date_options(db_path)
        date_from_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=d, text=d) for d in date_options],
        ]
        if date_from_dropdown.value not in {
            opt.key for opt in date_from_dropdown.options
        }:
            date_from_dropdown.value = _UNSELECTED
        date_to_dropdown.options = [
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=d, text=d) for d in date_options],
        ]
        if date_to_dropdown.value not in {opt.key for opt in date_to_dropdown.options}:
            date_to_dropdown.value = _UNSELECTED

    def refresh_filter_options() -> None:
        """取込タブでの取込完了時に外部から呼ばれ、バッチ/防具の選択肢を最新化する。

        ページ接続後にのみ呼ばれる想定（page.update()を呼ぶため）。
        """
        _load_filter_data()
        page.update()

    _load_filter_data()  # 初期表示（ページ未接続のためpage.update()は呼ばない）

    # --- バッチ指定/日付範囲指定の切り替え（ラジオボタン） ---
    # 初期状態はどちらも未選択（絞り込みなしの状態からスタート）。
    # 選択されていない側のドロップダウンはdisabledにして、どちらが有効かを分かりやすくする。
    batch_mode_radio = ft.Radio(value=_BATCH_MODE, label="対象バッチで指定")
    date_mode_radio = ft.Radio(value=_DATE_RANGE_MODE, label="取込日時の範囲で指定")

    def apply_batch_date_mode() -> None:
        mode = batch_date_mode_group.value
        batch_dropdown.disabled = mode != _BATCH_MODE
        date_from_dropdown.disabled = mode != _DATE_RANGE_MODE
        date_to_dropdown.disabled = mode != _DATE_RANGE_MODE

    def on_batch_date_mode_change(e: ft.Event[ft.RadioGroup]) -> None:
        apply_batch_date_mode()
        page.update()

    batch_date_mode_group = ft.RadioGroup(
        value=None,
        content=ft.Column(
            [
                ft.Row([batch_mode_radio, batch_dropdown]),
                ft.Row([date_mode_radio, date_from_dropdown, date_to_dropdown]),
            ],
            spacing=4,
        ),
    )
    batch_date_mode_group.on_change = on_batch_date_mode_change
    apply_batch_date_mode()  # 初期状態（未選択）に合わせてドロップダウンをdisabledにする

    threshold_dropdown = ft.Dropdown(
        label="必要な個数（1〜4）",
        width=160,
        value="1",
        options=[ft.DropdownOption(key=str(n), text=str(n)) for n in (1, 2, 3, 4)],
    )

    sort_dropdown = ft.Dropdown(
        label="並び替え",
        width=220,
        value=DEFAULT_SORT,
        options=[
            ft.DropdownOption(key="craft_order", text="練成順"),
            ft.DropdownOption(key="total_cost_desc", text="コスト（降順）"),
        ],
    )

    cost_min_dropdown = ft.Dropdown(
        label="コスト以上",
        width=140,
        value=_DEFAULT_COST_MIN,
        options=[ft.DropdownOption(key=n, text=n) for n in COST_OPTIONS],
    )
    cost_max_dropdown = ft.Dropdown(
        label="コスト以下",
        width=140,
        value=_DEFAULT_COST_MAX,
        options=[ft.DropdownOption(key=n, text=n) for n in COST_OPTIONS],
    )

    deficiency_dropdown = ft.Dropdown(
        label="スキル欠けの有無",
        width=160,
        value=_UNSELECTED,
        options=[
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            ft.DropdownOption(key="1", text="有"),
            ft.DropdownOption(key="0", text="無"),
        ],
    )

    resistance_min_dropdown = ft.Dropdown(
        label="耐性以上",
        width=140,
        value=_UNSELECTED,
        options=[
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=n, text=n) for n in RESISTANCE_OPTIONS],
        ],
    )
    resistance_max_dropdown = ft.Dropdown(
        label="耐性以下",
        width=140,
        value=_UNSELECTED,
        options=[
            ft.DropdownOption(key=_UNSELECTED, text="（未選択）"),
            *[ft.DropdownOption(key=n, text=n) for n in RESISTANCE_OPTIONS],
        ],
    )

    def condition_heading(text: str) -> ft.Control:
        # 検索ボタンほどではないが、他の項目より目に留まるよう色と大きさをつける
        return ft.Text(f"・{text}", size=15, weight=ft.FontWeight.BOLD, color=ft.Colors.BLUE_700)

    # --- 検索条件（コスト/防具/スキル）の折りたたみ ---
    condition_section = ft.Column(
        [
            condition_heading("コスト"),
            ft.Row([cost_min_dropdown, cost_max_dropdown]),
            condition_heading("防具"),
            ft.Row([label_dropdown]),
            condition_heading("スキル"),
            ft.Row(
                [
                    current_set_dropdown,
                    current_set_detail_button,
                    ft.Text("に含まれるスキルが"),
                    threshold_dropdown,
                    ft.Text("個以上含まれる結果を検索"),
                    select_skill_button,
                ]
            ),
            condition_heading("スキル欠け"),
            ft.Row([deficiency_dropdown]),
            condition_heading("耐性"),
            ft.Row([resistance_min_dropdown, resistance_max_dropdown]),
        ],
        spacing=6,
        visible=False,
    )

    def toggle_condition_section(e: ft.Event[ft.Button]) -> None:
        condition_section.visible = not condition_section.visible
        condition_toggle_button.content = (
            "検索条件を閉じる" if condition_section.visible else "検索条件を変更"
        )
        page.update()

    # 検索ボタンほどではないが、少し目立つように色をつける
    condition_toggle_button = ft.Button(
        content="検索条件を変更",
        on_click=toggle_condition_section,
        bgcolor=ft.Colors.BLUE_50,
        color=ft.Colors.BLUE_700,
    )

    progress_bar = ft.ProgressBar(width=420, value=0, visible=False)
    status_text = ft.Text()
    # ListView（独立スクロール）にすると外側Columnのスクロールと競合し、
    # 固定高さの中でしかスクロールできず一部の行しか見えなくなるため、
    # 外側1本のスクロールに統合されるColumnに戻す。
    # ページあたり最大200件までしか描画しないため、Columnでも表示は軽い。
    results_list = ft.Column(spacing=2)

    # 検索ボタンは一番の主操作なので、他のボタンよりはっきり目立つ見た目にする
    search_button = ft.Button(
        content=ft.Text("検索", size=18, weight=ft.FontWeight.BOLD),
        icon=ft.Icons.SEARCH,
        bgcolor=ft.Colors.BLUE_600,
        color=ft.Colors.WHITE,
        height=48,
        width=180,
    )
    prev_button_top = ft.Button(content="前へ", disabled=True)
    next_button_top = ft.Button(content="次へ", disabled=True)
    prev_button_bottom = ft.Button(content="前へ", disabled=True)
    next_button_bottom = ft.Button(content="次へ", disabled=True)
    prev_buttons = (prev_button_top, prev_button_bottom)
    next_buttons = (next_button_top, next_button_bottom)

    current_offset = 0
    has_next_page = False

    def set_busy(busy: bool) -> None:
        search_button.disabled = busy
        for btn in prev_buttons:
            btn.disabled = busy or current_offset <= 0
        for btn in next_buttons:
            btn.disabled = busy or not has_next_page
        progress_bar.visible = busy
        page.update()

    def make_collected_checkbox(
        result_id: int, batch_id: int, initial: bool
    ) -> ft.Checkbox:
        checkbox = ft.Checkbox(value=initial)

        def on_change(e: ft.Event[ft.Checkbox]) -> None:
            checked = bool(checkbox.value)
            conn = get_connection(db_path)
            try:
                try:
                    set_collected(conn, result_id, batch_id, checked)
                except CollectionLimitError as exc:
                    checkbox.value = (
                        False  # 上限超過は必ず「チェックしようとした」失敗なので戻す
                    )
                    status_text.value = str(exc)
                    checked = False
            finally:
                conn.close()
            page.update()
            if checked and on_collected is not None:
                on_collected(batch_id)  # 回収確認サイドパネルを自動的に開く

        checkbox.on_change = on_change
        return checkbox

    def render_results(rows, breakdown: dict[int, list[tuple[str, int]]]) -> None:
        results_list.controls.clear()

        if not rows:
            results_list.controls.append(ft.Text("該当する結果はありません"))
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
                ft.Text("バッチ", width=60, weight=ft.FontWeight.BOLD),
                ft.Text("取込日時", width=160, weight=ft.FontWeight.BOLD),
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
                            ft.Text(str(row.batch_id), width=60),
                            ft.Text(row.imported_at, width=160),
                            make_collected_checkbox(
                                row.id, row.batch_id, bool(row.collected)
                            ),
                        ]
                    ),
                    # ゼブラストライプ: 1行おきに背景色を変えて行を目で追いやすくする
                    bgcolor=ft.Colors.SURFACE_CONTAINER_HIGHEST
                    if index % 2 == 1
                    else None,
                    padding=ft.Padding.symmetric(vertical=2, horizontal=4),
                )
            )
        page.update()

    def build_current_params(offset: int) -> SearchParams | None:
        try:
            min_total_cost = int(cost_min_dropdown.value or _DEFAULT_COST_MIN)
            max_total_cost = int(cost_max_dropdown.value or _DEFAULT_COST_MAX)
        except ValueError:
            status_text.value = "コストの指定が不正です"
            page.update()
            return None
        if min_total_cost > max_total_cost:
            status_text.value = "「コスト以上」は「コスト以下」より大きくできません"
            page.update()
            return None

        min_resistance = (
            int(resistance_min_dropdown.value)
            if resistance_min_dropdown.value and resistance_min_dropdown.value != _UNSELECTED
            else None
        )
        max_resistance = (
            int(resistance_max_dropdown.value)
            if resistance_max_dropdown.value and resistance_max_dropdown.value != _UNSELECTED
            else None
        )
        if min_resistance is not None and max_resistance is not None and min_resistance > max_resistance:
            status_text.value = "「耐性以上」は「耐性以下」より大きくできません"
            page.update()
            return None

        mode = batch_date_mode_group.value

        # 検索に使うスキル集合は、ダイアログ内のチェックボックスではなく
        # current_set_dropdownの選択内容をDBから読み直したものを使う
        # （スキル未選択でもよい。その場合は他の条件のみで検索する）。
        selected_names: list[str] = []
        if current_set_dropdown.value and current_set_dropdown.value != _UNSELECTED:
            conn = get_connection(db_path)
            try:
                selected_names = get_skill_set(conn, current_set_dropdown.value) or []
            finally:
                conn.close()

        conn = get_connection(db_path)
        try:
            registry = SkillRegistry(conn)
            allowed_ids = registry.get_ids(selected_names)
        finally:
            conn.close()

        return SearchParams(
            allowed_skill_ids=allowed_ids,
            threshold=int(threshold_dropdown.value or 1),
            sort=sort_dropdown.value or DEFAULT_SORT,
            date_from=(
                date_from_dropdown.value
                if mode == _DATE_RANGE_MODE
                and date_from_dropdown.value
                and date_from_dropdown.value != _UNSELECTED
                else None
            ),
            # 終了日はその日の終わりまでを含めるため、日末時刻を補完する
            date_to=(
                f"{date_to_dropdown.value}T23:59:59"
                if mode == _DATE_RANGE_MODE
                and date_to_dropdown.value
                and date_to_dropdown.value != _UNSELECTED
                else None
            ),
            batch_id=(
                int(batch_dropdown.value)
                if mode == _BATCH_MODE
                and batch_dropdown.value
                and batch_dropdown.value != _UNSELECTED
                else None
            ),
            label=(
                label_dropdown.value
                if label_dropdown.value and label_dropdown.value != _UNSELECTED
                else None
            ),
            min_total_cost=min_total_cost,
            max_total_cost=max_total_cost,
            has_deficiency=(
                int(deficiency_dropdown.value)
                if deficiency_dropdown.value and deficiency_dropdown.value != _UNSELECTED
                else None
            ),
            min_resistance=min_resistance,
            max_resistance=max_resistance,
            # 1件多く取得し、201件目があれば「次へ」を有効にする（COUNT(*)を避けるため）
            limit=_PAGE_SIZE + 1,
            offset=offset,
        )

    async def scroll_to_anchor() -> None:
        # scroll_to()は非同期APIのため、ワーカースレッド（page.run_thread）からは
        # page.run_task()経由でページのイベントループ上に実行を依頼する。
        # duration=0で即時ジャンプにし、アニメーション分の固定遅延をなくす。
        await view.scroll_to(scroll_key=_SCROLL_ANCHOR_KEY, duration=0)

    def run_search_page(offset: int) -> None:
        nonlocal current_offset, has_next_page

        params = build_current_params(offset)
        if params is None:
            return

        set_busy(True)
        status_text.value = "検索中..."
        page.update()

        conn = get_connection(db_path)
        try:
            rows = search_results(conn, params)
            has_next_page = len(rows) > _PAGE_SIZE
            rows = rows[:_PAGE_SIZE]
            breakdown = fetch_skill_breakdown(conn, [r.id for r in rows])
        finally:
            conn.close()

        current_offset = offset
        status_text.value = (
            f"検索結果: {current_offset + 1}〜{current_offset + len(rows)}件目を表示中"
            if rows
            else "検索結果: 該当する結果はありません"
        )
        page.update()
        render_results(rows, breakdown)
        set_busy(False)
        page.run_task(scroll_to_anchor)

    def on_search_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_search_page, 0)

    def on_prev_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_search_page, max(0, current_offset - _PAGE_SIZE))

    def on_next_click(e: ft.Event[ft.Button]) -> None:
        page.run_thread(run_search_page, current_offset + _PAGE_SIZE)

    search_button.on_click = on_search_click
    for btn in prev_buttons:
        btn.on_click = on_prev_click
    for btn in next_buttons:
        btn.on_click = on_next_click

    def show_missing_skill_set_warning(skill_set_name: str) -> None:
        def close_warning(e: ft.Event[ft.Button]) -> None:
            page.pop_dialog()

        dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("スキル集合が見つかりません"),
            content=ft.Text(
                f"この防具の検索初期設定に登録されているスキル集合「{skill_set_name}」が"
                "見つからなかったため、スキル未選択で検索しました。\n\n"
                "（設定タブの「防具ごとの検索初期設定」で登録し直してください）"
            ),
            actions=[ft.Button(content="閉じる", on_click=close_warning)],
        )
        page.show_dialog(dialog)

    def select_batch_and_search(
        batch_id: int, defaults: ArmorSearchDefaults | None = None
    ) -> None:
        """取込タブ・履歴タブから呼ばれ、指定バッチのみを対象に検索する。

        defaultsが指定された場合（取込タブから、防具ごとの検索初期設定が
        ある場合に呼ばれる）は、コスト/耐性/スキル欠け/しきい値/並び替え/
        スキル集合をその内容で復元する。指定されない場合（履歴タブからの
        遷移時）は、従来通りすべて既定値にリセットする。
        """
        do_clear_selection()

        if defaults is not None:
            cost_min_dropdown.value = str(defaults.min_total_cost)
            cost_max_dropdown.value = str(defaults.max_total_cost)
            resistance_min_dropdown.value = (
                str(defaults.min_resistance) if defaults.min_resistance is not None else _UNSELECTED
            )
            resistance_max_dropdown.value = (
                str(defaults.max_resistance) if defaults.max_resistance is not None else _UNSELECTED
            )
            deficiency_dropdown.value = (
                str(defaults.has_deficiency) if defaults.has_deficiency is not None else _UNSELECTED
            )
            threshold_dropdown.value = str(defaults.threshold)
            sort_dropdown.value = defaults.sort

            if defaults.skill_set_name:
                conn = get_connection(db_path)
                try:
                    skill_set_exists = get_skill_set(conn, defaults.skill_set_name) is not None
                finally:
                    conn.close()
                if skill_set_exists:
                    current_set_dropdown.value = defaults.skill_set_name
                else:
                    current_set_dropdown.value = _UNSELECTED
                    show_missing_skill_set_warning(defaults.skill_set_name)
            else:
                current_set_dropdown.value = _UNSELECTED
        else:
            cost_min_dropdown.value = _DEFAULT_COST_MIN
            cost_max_dropdown.value = _DEFAULT_COST_MAX
            resistance_min_dropdown.value = _UNSELECTED
            resistance_max_dropdown.value = _UNSELECTED
            deficiency_dropdown.value = _UNSELECTED
            threshold_dropdown.value = "1"
            sort_dropdown.value = DEFAULT_SORT
            current_set_dropdown.value = _UNSELECTED

        label_dropdown.value = _UNSELECTED
        date_from_dropdown.value = _UNSELECTED
        date_to_dropdown.value = _UNSELECTED
        condition_section.visible = False
        condition_toggle_button.content = "検索条件を変更"

        _load_filter_data()  # 対象バッチが選択肢に確実に含まれるようにする
        batch_date_mode_group.value = _BATCH_MODE
        batch_dropdown.value = str(batch_id)
        apply_batch_date_mode()

        page.update()
        page.run_thread(run_search_page, 0)

    view = ft.Column(
        [
            ft.Text(
                "錬成結果の検索",
                size=20,
                weight=ft.FontWeight.BOLD,
                key=_SCROLL_ANCHOR_KEY,
            ),
            ft.Text("検索を行うバッチの指定", weight=ft.FontWeight.BOLD),
            ft.Container(
                content=batch_date_mode_group, padding=ft.Padding.only(left=24)
            ),
            ft.Text("ソート", weight=ft.FontWeight.BOLD),
            ft.Container(content=sort_dropdown, padding=ft.Padding.only(left=24)),
            ft.Text("条件指定", weight=ft.FontWeight.BOLD),
            ft.Container(
                content=condition_toggle_button, padding=ft.Padding.only(left=24)
            ),
            ft.Container(content=condition_section, padding=ft.Padding.only(left=48)),
            ft.Row([search_button]),
            progress_bar,
            status_text,
            ft.Row([prev_button_top, next_button_top]),
            ft.Divider(),
            results_list,
            ft.Divider(),
            ft.Row([prev_button_bottom, next_button_bottom]),
        ],
        expand=True,
        scroll=ft.ScrollMode.AUTO,
    )
    return view, refresh_filter_options, select_batch_and_search
