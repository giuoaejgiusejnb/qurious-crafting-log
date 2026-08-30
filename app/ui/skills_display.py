import flet as ft

from app.core.skill_colors import DEFAULT_NEGATIVE_COLOR, DEFAULT_POSITIVE_COLOR, resolve_color

_SKILLS_COLUMN_WIDTH = 240


def build_skills_wrap(
    skills: list[tuple[str, int]],
    width: int = _SKILLS_COLUMN_WIDTH,
    positive_color: str = DEFAULT_POSITIVE_COLOR,
    negative_color: str = DEFAULT_NEGATIVE_COLOR,
) -> ft.Control:
    """検索結果一覧・回収一覧のスキル内訳セルを組み立てる。

    「名前＋値」を「、」区切りで並べて表示するが、単純に1つのft.Textへ連結すると、
    日本語テキストの行間はどこでも改行可能とみなされ、指定した幅で折り返す際に
    スキル名の途中で改行されてしまうことがある（例:「散弾」が「散」「弾」に分断される）。
    スキルごとに独立したft.Textとして並べ、ft.Row(wrap=True)で折り返すことで、
    スキルの区切り（「、」の直後）でしか改行されないようにする。

    positive_color/negative_colorはapp/core/skill_colors.pyの色キー
    （設定タブで変更可能）。呼び出し側でDBから読み込んで渡す想定。
    """
    if not skills:
        return ft.Container(width=width)

    resolved_positive = resolve_color(positive_color)
    resolved_negative = resolve_color(negative_color)

    controls: list[ft.Control] = []
    for i, (name, value) in enumerate(skills):
        text = f"{name}{value:+d}"
        if i < len(skills) - 1:
            text += "、"
        controls.append(
            ft.Text(
                text,
                color=resolved_negative if value < 0 else resolved_positive,
            )
        )
    return ft.Row(controls, wrap=True, spacing=0, run_spacing=0, width=width)
