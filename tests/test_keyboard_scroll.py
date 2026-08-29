import app.ui.keyboard_scroll as keyboard_scroll
from app.ui.keyboard_scroll import guard_focus, is_input_focused


class _FakeControl:
    """ft.Controlの代わりに使う最小限のダミー（on_focus/on_blur属性のみ持つ）。"""

    def __init__(self):
        self.on_focus = None
        self.on_blur = None


def _reset_focus_count():
    keyboard_scroll._focus_count = 0


def test_is_input_focused_false_initially():
    _reset_focus_count()
    assert is_input_focused() is False


def test_is_input_focused_true_while_focused():
    _reset_focus_count()
    control = guard_focus(_FakeControl())

    control.on_focus(None)
    assert is_input_focused() is True

    control.on_blur(None)
    assert is_input_focused() is False


def test_is_input_focused_true_while_any_of_multiple_controls_focused():
    _reset_focus_count()
    control_a = guard_focus(_FakeControl())
    control_b = guard_focus(_FakeControl())

    control_a.on_focus(None)
    control_b.on_focus(None)
    assert is_input_focused() is True

    control_a.on_blur(None)
    assert is_input_focused() is True  # bはまだフォーカス中

    control_b.on_blur(None)
    assert is_input_focused() is False


def test_is_input_focused_does_not_go_negative_on_extra_blur():
    _reset_focus_count()
    control = guard_focus(_FakeControl())

    control.on_blur(None)  # focusを伴わないblurが来ても壊れない
    control.on_blur(None)
    assert is_input_focused() is False


def test_guard_focus_chains_existing_handlers():
    _reset_focus_count()
    calls = []
    control = _FakeControl()
    control.on_focus = lambda e: calls.append("existing_focus")
    control.on_blur = lambda e: calls.append("existing_blur")
    guard_focus(control)

    control.on_focus(None)
    control.on_blur(None)

    assert calls == ["existing_focus", "existing_blur"]
