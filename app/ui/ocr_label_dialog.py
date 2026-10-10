"""画像読み取り（8bit）で、ラベルが確定していない見本の正しいラベルをユーザーに入力してもらうダイアログ。

1. 入力画面: 見本ごとに画像とラベルの選択欄を並べる。すべて選ぶまで「入力したラベルで続ける」は押せない
2. 確認画面: 画像と選んだラベルを並べて表示する（変更不可）。「この内容で確定」で見本のラベルが確定する。
   「戻って修正する」で入力画面に戻る
どちらの画面でも「取込を中止」で何も保存せずにやめられる。
"""

from typing import TYPE_CHECKING, Callable

import flet as ft

if TYPE_CHECKING:
    from app.ocr.kuijin_ocr import PendingLabel

# ラベル "" （ノイズ）はドロップダウンのキーに使いにくいので置き換える
_NOISE_KEY = "__noise__"
_NOISE_TEXT = "ノイズ（無視する）"
_KIND_ORDER = ("name", "slot", "glyph", "money_glyph")

# 入力結果 {(見本の名前, 番号): ラベル}。None は「取込を中止」
LabelsCallback = Callable[[dict[tuple[str, int], str] | None], None]


def _kind_note(kind: str, base_slot: int) -> str:
    if kind == "name":
        return "画像のスキル名を選んでください（文字を入力すると絞り込めます）"
    if kind == "slot":
        return f"初期スロット {base_slot} から増えたスロットの数を選んでください（画像は練成後のスロット）"
    return "赤枠の 1 文字が何か選んでください（右は切り取った文字を拡大したもの）。演出の粒などはノイズ"


def _label_text(label: str) -> str:
    return _NOISE_TEXT if label == "" else label


def _images(item: "PendingLabel") -> list[ft.Control]:
    images: list[ft.Control] = [ft.Image(src=item.image_png)]
    if item.glyph_png:
        images.append(ft.Image(src=item.glyph_png))
    return images


def _count_text(item: "PendingLabel") -> ft.Text:
    return ft.Text(f"{item.count}枚の画像に出現" if item.count else "", size=12, color=ft.Colors.GREY_700)


def show_label_dialog(
    page: ft.Page, pending: "list[PendingLabel]", base_slot: int, on_done: LabelsCallback
) -> None:
    """pending の見本ごとにラベルを選んでもらい、確認画面で確定したら on_done に渡す。

    「この内容で確定」ですべての見本のラベルを on_done に渡す。「取込を中止」は None を渡す。
    """
    from app.ocr.kuijin_ocr import KIND_TITLES, label_choices

    items = [p for kind in _KIND_ORDER for p in pending if p.kind == kind]
    dropdowns: dict[tuple[str, int], ft.Dropdown] = {}
    error_text = ft.Text("", color=ft.Colors.RED_700)
    progress_text = ft.Text("", size=12)

    def selected_labels() -> dict[tuple[str, int], str]:
        """選択済みで、一覧にあるラベルだけを返す。"""
        labels = {}
        for item in items:
            value = dropdowns[item.key].value
            if not value:
                continue
            label = "" if value == _NOISE_KEY else value
            if label in label_choices(item.kind):
                labels[item.key] = label
        return labels

    def refresh_submit_state(e: ft.Event[ft.Dropdown] | None = None) -> None:
        done = len(selected_labels())
        submit_button.disabled = done < len(items)
        progress_text.value = f"{done} / {len(items)} 個選択済み"
        if e is not None:
            page.update()

    def section_header(kind: str, count: int) -> list[ft.Control]:
        return [
            ft.Text(f"{KIND_TITLES[kind]}（{count}個）", weight=ft.FontWeight.BOLD, size=16),
            ft.Text(_kind_note(kind, base_slot), size=12, color=ft.Colors.GREY_700),
        ]

    # --- 入力画面 ---
    input_sections: list[ft.Control] = [
        ft.Text("これまでの見本と一致しない表示がありました。画像を見て正しいものを選んでください。"
                "選んだラベルは次回以降の読み取りにも使われます。"),
        ft.Divider(),
    ]
    for kind in _KIND_ORDER:
        kind_items = [p for p in items if p.kind == kind]
        if not kind_items:
            continue
        input_sections += section_header(kind, len(kind_items))
        for item in kind_items:
            dropdown = ft.Dropdown(
                options=[
                    ft.DropdownOption(key=c if c else _NOISE_KEY, text=_label_text(c))
                    for c in label_choices(kind)
                ],
                value=item.guess or None,
                width=240 if kind == "name" else 180,
                enable_filter=kind == "name",
                editable=kind == "name",
                menu_height=320,
                label="ラベル",
                on_select=refresh_submit_state,
            )
            dropdowns[item.key] = dropdown
            input_sections.append(
                ft.Row(
                    [*_images(item), ft.Column([dropdown, _count_text(item)], spacing=2)],
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                )
            )
        input_sections.append(ft.Divider())
    input_sections.append(error_text)

    # --- 確認画面（入力画面から「入力したラベルで続ける」で作り直す） ---
    confirm_column = ft.Column(spacing=8)

    def build_confirm(labels: dict[tuple[str, int], str]) -> None:
        controls: list[ft.Control] = [
            ft.Text("以下の内容で見本のラベルを確定します。よろしければ「この内容で確定」を押してください。"),
            ft.Divider(),
        ]
        for kind in _KIND_ORDER:
            kind_items = [p for p in items if p.kind == kind]
            if not kind_items:
                continue
            controls.append(ft.Text(f"{KIND_TITLES[kind]}（{len(kind_items)}個）", weight=ft.FontWeight.BOLD, size=16))
            for item in kind_items:
                controls.append(
                    ft.Row(
                        [
                            *_images(item),
                            ft.Container(
                                content=ft.Text(_label_text(labels[item.key]), size=18, weight=ft.FontWeight.BOLD),
                                bgcolor=ft.Colors.BLUE_50,
                                border_radius=6,
                                padding=ft.Padding.symmetric(horizontal=12, vertical=6),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    )
                )
            controls.append(ft.Divider())
        confirm_column.controls = controls

    content = ft.Column(scroll=ft.ScrollMode.AUTO, tight=True, width=880, height=540)

    async def scroll_to_top() -> None:
        # 入力画面と確認画面は同じ Column の中身を入れ替えるため、スクロール位置が残る。
        # 切り替えたら先頭に戻す（scroll_to は非同期 API なので page.run_task 経由で呼ぶ）
        await content.scroll_to(offset=0, duration=0)

    def show_input() -> None:
        dialog.title = ft.Text(f"新しい見本の確認（{len(items)}個）")
        content.controls = input_sections
        dialog.actions = [cancel_button, progress_text, submit_button]
        refresh_submit_state()

    def on_submit(e: ft.Event[ft.Button]) -> None:
        labels = selected_labels()
        invalid = [
            dropdowns[item.key].value
            for item in items
            if item.key not in labels and dropdowns[item.key].value
        ]
        if invalid:
            error_text.value = f"一覧にないラベルがあります: {'、'.join(str(v) for v in invalid)}"
            page.update()
            return
        if len(labels) < len(items):
            return
        error_text.value = ""
        build_confirm(labels)
        dialog.title = ft.Text("ラベルの確認")
        content.controls = [confirm_column]
        dialog.actions = [cancel_button, back_button, confirm_button]
        confirmed_labels.clear()
        confirmed_labels.update(labels)
        page.update()
        page.run_task(scroll_to_top)

    def on_back(e: ft.Event[ft.TextButton]) -> None:
        show_input()
        page.update()
        page.run_task(scroll_to_top)

    def on_confirm(e: ft.Event[ft.Button]) -> None:
        page.pop_dialog()
        on_done(dict(confirmed_labels))

    def on_cancel(e: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()
        on_done(None)

    confirmed_labels: dict[tuple[str, int], str] = {}
    cancel_button = ft.TextButton(content="取込を中止", on_click=on_cancel)
    submit_button = ft.Button(content="入力したラベルで続ける", on_click=on_submit)
    back_button = ft.TextButton(content="戻って修正する", on_click=on_back)
    confirm_button = ft.Button(content="この内容で確定", on_click=on_confirm)

    dialog = ft.AlertDialog(modal=True, content=content)
    show_input()
    page.show_dialog(dialog)
