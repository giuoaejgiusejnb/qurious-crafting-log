"""画像読み取り（8bit）の画像を 1 枚ずつ見てもらうダイアログ。

- 確認が必要なため取り込まなかった画像（show_unread_viewer）: 読めない値がある行や、読み取った内容に疑わしい点が
  ある行は DB に入れない（検索にも出ない）。代わりに、何回目の練成か・ゼニー・画像を見せて、ユーザーに直接
  確かめてもらう（何が疑わしいかは出さない。画像に答えがある）
- 取り込んだ結果の画像（show_result_image_viewer）: 検索結果や回収の画面から、その結果を読み取った画像を見る

画像は取り込んだときのフォルダから読むので、移動・削除していると表示できない。
"""

import os
import subprocess
from pathlib import Path
from typing import Callable

import flet as ft

# (練成回数 or None, ゼニー（千単位） or None, 画像のパス, 正確なゼニー or None)
ImageItem = tuple[int | None, int | None, str, int | None]


def open_in_explorer(path: str) -> None:
    """エクスプローラーで、画像を選んだ状態でそのフォルダを開く。画像が無ければ、フォルダだけを開く。"""
    target = Path(path)
    if target.exists():
        # explorer は成功しても終了コード 1 を返すので、結果は見ない
        subprocess.Popen(["explorer", f"/select,{os.path.normpath(target)}"])
    elif target.parent.exists():
        subprocess.Popen(["explorer", os.path.normpath(target.parent)])


def zeny_text(zeny: int | None, exact: int | None) -> str:
    """ゼニーの表示。正確な値（下 3 桁まで）が分かればそれを、千単位の値しか無ければ「千」を付けて出す。

    ほかの画面のゼニーは千単位（NX Macro Controller のテキストが千単位のため）。ここは画像読み取りでしか出ず、
    ゲームの画面と見比べる場所なので、正確な値を出す。正確な値を保存していなかった頃のバッチは千単位しか無い。
    """
    if exact is not None:
        return f"{exact:,}"
    return f"{zeny:,}千" if zeny is not None else "不明"


def image_button(on_click: Callable[[], None]) -> ft.IconButton:
    """結果の行に置く、その結果の画像を見るボタン。"""
    return ft.IconButton(icon=ft.Icons.IMAGE_OUTLINED, icon_size=18, tooltip="この結果の画像を見る",
                         on_click=lambda e: on_click())


def show_unread_viewer(
    page: ft.Page,
    items: list[ImageItem],
    batch_id: int | None = None,
    on_close: Callable[[], None] | None = None,
) -> None:
    """確認が必要なため取り込まなかった画像を、回数の順に 1 枚ずつ表示する。

    on_close は「閉じる」で閉じた後に呼ぶ（取込の直後に、続きの確認へ戻るため）。
    """
    where = f"バッチ #{batch_id} の" if batch_id is not None else ""
    _show_viewer(
        page,
        sorted(items, key=lambda item: (item[0] is None, item[0] or 0, item[2])),
        f"{where}確認が必要な画像",
        "読み取れない値があったか、読み取った内容に疑わしい点があったため、この結果は取り込んでいません"
        "（検索にも出ません）。画像を見て確認してください。",
        on_close=on_close,
    )


def show_result_image_viewer(page: ft.Page, items: list[ImageItem], start: int = 0) -> None:
    """取り込んだ結果の画像を、items の並びのまま、start 番目から 1 枚ずつ表示する。"""
    _show_viewer(page, items, "取り込んだ結果の画像", None, start=start)


def _show_viewer(
    page: ft.Page,
    items: list[ImageItem],
    heading: str,
    note: str | None,
    start: int = 0,
    on_close: Callable[[], None] | None = None,
) -> None:
    # 画像読み取りの依存（numpy / OpenCV）は重いので、使うときだけ読み込む
    from app.ocr.kuijin_ocr import result_view_png

    position = [start]
    title = ft.Text("")
    # 何回目の練成かとゼニーは、ゲームの中でその結果を探す手がかりなので、大きく出す
    headline = ft.Text("", size=24, weight=ft.FontWeight.BOLD, selectable=True)
    path_button = ft.TextButton(content="", icon=ft.Icons.FOLDER_OPEN, tooltip="エクスプローラーで画像の場所を開く",
                                on_click=lambda e: open_in_explorer(items[position[0]][2]))
    image_holder = ft.Container()   # 画像は 1 枚ごとに作り直す
    missing = ft.Text("", color=ft.Colors.RED_700, selectable=True, visible=False)

    def render() -> None:
        count, zeny, path, exact = items[position[0]]
        title.value = f"{heading}（{position[0] + 1} / {len(items)}）"
        headline.value = (
            (f"{count}回目" if count is not None else "回数不明")
            + "　　ゼニー："
            + zeny_text(zeny, exact)
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
                *([ft.Text(note, size=12)] if note else []),
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
