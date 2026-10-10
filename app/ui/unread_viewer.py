"""画像読み取り（8bit）で読めない値があり、取り込めなかった画像を 1 枚ずつ見てもらうダイアログ。

読めない値のある行は DB に入れない（検索にも出ない）。代わりに、何回目の練成か・ゼニー・画像を見せて、
ユーザーに直接確かめてもらう。画像は取り込んだときのフォルダから読むので、移動・削除していると表示できない。
"""

import os
import subprocess
from pathlib import Path
from typing import Callable

import flet as ft


def open_in_explorer(path: str) -> None:
    """エクスプローラーで、画像を選んだ状態でそのフォルダを開く。画像が無ければ、フォルダだけを開く。"""
    target = Path(path)
    if target.exists():
        # explorer は成功しても終了コード 1 を返すので、結果は見ない
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(target)}"])
    elif target.parent.exists():
        subprocess.Popen(["explorer", os.path.normpath(target.parent)])


def show_unread_viewer(
    page: ft.Page,
    items: list[tuple[int | None, int | None, str]],
    batch_id: int | None = None,
    on_close: Callable[[], None] | None = None,
) -> None:
    """items（[(練成回数 or None, ゼニー or None, 画像のパス), ...]）を、回数の順に 1 枚ずつ表示する。

    on_close は「閉じる」で閉じた後に呼ぶ（取込の直後に、続きの確認へ戻るため）。
    """
    # 画像読み取りの依存（numpy / OpenCV）は重いので、使うときだけ読み込む
    from app.ocr.kuijin_ocr import result_view_png

    items = sorted(items, key=lambda item: (item[0] is None, item[0] or 0, item[2]))
    position = [0]
    title = ft.Text("")
    # 何回目の練成かとゼニーは、ゲームの中でその結果を探す手がかりなので、大きく出す
    headline = ft.Text("", size=24, weight=ft.FontWeight.BOLD, selectable=True)
    path_button = ft.TextButton(content="", icon=ft.Icons.FOLDER_OPEN, tooltip="エクスプローラーで画像の場所を開く",
                                on_click=lambda e: open_in_explorer(items[position[0]][2]))
    image_holder = ft.Container()   # 画像は 1 枚ごとに作り直す
    missing = ft.Text("", color=ft.Colors.RED_700, selectable=True, visible=False)

    def render() -> None:
        count, zeny, path = items[position[0]]
        where = f"バッチ #{batch_id} の" if batch_id is not None else ""
        title.value = f"{where}読めなかった画像（{position[0] + 1} / {len(items)}）"
        headline.value = (
            (f"{count}回目" if count is not None else "回数不明")
            + "　　ゼニー："
            + (str(zeny) if zeny is not None else "不明")
        )
        path_button.content = path
        png = result_view_png(path)
        image_holder.content = ft.Image(src=png) if png is not None else None
        missing.visible = png is None
        if png is None:
            missing.value = "画像を表示できません（フォルダを移動・削除した場合は表示できません）"
        prev_button.disabled = position[0] == 0
        next_button.disabled = position[0] == len(items) - 1

    def move(step: int) -> None:
        position[0] = min(max(position[0] + step, 0), len(items) - 1)
        render()
        page.update()

    def close(e: ft.Event[ft.TextButton]) -> None:
        page.pop_dialog()
        if on_close is not None:
            on_close()

    prev_button = ft.TextButton(content="前へ", on_click=lambda e: move(-1))
    next_button = ft.Button(content="次へ", on_click=lambda e: move(1))
    dialog = ft.AlertDialog(
        modal=True,
        title=title,
        content=ft.Column(
            [
                ft.Text("読み取れない値があったため、この結果は取り込んでいません（検索にも出ません）。"
                        "画像を見て確認してください。", size=12),
                headline,
                image_holder,
                missing,
                path_button,
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            tight=True,
            width=680,
            height=660,
        ),
        actions=[ft.TextButton(content="閉じる", on_click=close), prev_button, next_button],
    )
    render()
    page.show_dialog(dialog)
