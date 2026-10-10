"""画像読み取り（8bit）で読めない値があり、取り込めなかった画像を 1 枚ずつ見てもらうダイアログ。

読めない値のある行は DB に入れない（検索にも出ない）。代わりに、何回目の練成かと画像を見せて、
ユーザーに直接確かめてもらう。画像は取り込んだときのフォルダから読むので、移動・削除していると表示できない。
"""

from pathlib import Path

import flet as ft


def show_unread_viewer(page: ft.Page, items: list[tuple[int | None, str]], batch_id: int | None = None) -> None:
    """items（[(練成回数 or None, 画像のパス), ...]）を、回数の順に 1 枚ずつ表示する。"""
    # 画像読み取りの依存（numpy / OpenCV）は重いので、使うときだけ読み込む
    from app.ocr.kuijin_ocr import result_view_png

    items = sorted(items, key=lambda item: (item[0] is None, item[0] or 0, item[1]))
    position = [0]
    title = ft.Text("")
    caption = ft.Text("", selectable=True)
    image_holder = ft.Container()   # 画像は 1 枚ごとに作り直す
    missing = ft.Text("", color=ft.Colors.RED_700, selectable=True, visible=False)

    def render() -> None:
        count, path = items[position[0]]
        where = f"バッチ #{batch_id} の" if batch_id is not None else ""
        title.value = f"{where}読めなかった画像（{position[0] + 1} / {len(items)}）"
        caption.value = (f"{count}回目" if count is not None else "回数不明（所持ゼニーが読めません）") + f"　{Path(path).name}"
        png = result_view_png(path)
        image_holder.content = ft.Image(src=png) if png is not None else None
        missing.visible = png is None
        if png is None:
            missing.value = f"画像を表示できません（フォルダを移動・削除した場合は表示できません）:\n{path}"
        prev_button.disabled = position[0] == 0
        next_button.disabled = position[0] == len(items) - 1

    def move(step: int) -> None:
        position[0] = min(max(position[0] + step, 0), len(items) - 1)
        render()
        page.update()

    prev_button = ft.TextButton(content="前へ", on_click=lambda e: move(-1))
    next_button = ft.Button(content="次へ", on_click=lambda e: move(1))
    dialog = ft.AlertDialog(
        modal=True,
        title=title,
        content=ft.Column(
            [
                ft.Text("読み取れない値があったため、この結果は取り込んでいません（検索にも出ません）。"
                        "画像を見て確認してください。", size=12),
                caption,
                image_holder,
                missing,
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
            width=680,
            height=620,
        ),
        actions=[ft.TextButton(content="閉じる", on_click=lambda e: page.pop_dialog()), prev_button, next_button],
    )
    render()
    page.show_dialog(dialog)
