"""キーボードの上下キー/PageUp/PageDownで画面をスクロールする機能の共通部品。

ドロップダウンやテキスト欄にフォーカスがある間は、そのコントロール自身の操作
（ドロップダウンの選択肢移動やカーソル移動）を優先し、ページ全体のスクロールは
抑止する。フォーカス中のコントロール数をカウンタで管理することで、複数の
コントロール間でフォーカスが移り変わる際の順序（blur→focusかfocus→blurか）に
依存せず正しく判定できるようにしている。
"""

from typing import TypeVar

import flet as ft

_ControlT = TypeVar("_ControlT", bound=ft.Control)

_focus_count = 0


def is_input_focused() -> bool:
    """いずれかのコントロールがフォーカス中ならTrue（この間はページスクロールを抑止する）。"""
    return _focus_count > 0


def _on_focus(e: ft.Event[ft.Control]) -> None:
    global _focus_count
    _focus_count += 1


def _on_blur(e: ft.Event[ft.Control]) -> None:
    global _focus_count
    _focus_count = max(0, _focus_count - 1)


def guard_focus(control: _ControlT) -> _ControlT:
    """ドロップダウン/テキスト欄に付与し、フォーカス中はキーボードスクロールを止める。

    既存のon_focus/on_blurがあれば、それも壊さないよう連鎖して呼び出す。
    """
    existing_on_focus = control.on_focus
    existing_on_blur = control.on_blur

    def on_focus(e: ft.Event[ft.Control]) -> None:
        _on_focus(e)
        if existing_on_focus is not None:
            existing_on_focus(e)

    def on_blur(e: ft.Event[ft.Control]) -> None:
        _on_blur(e)
        if existing_on_blur is not None:
            existing_on_blur(e)

    control.on_focus = on_focus
    control.on_blur = on_blur
    return control
