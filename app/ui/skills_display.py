import flet as ft

_SKILLS_COLUMN_WIDTH = 240


def build_skills_wrap(skills: list[tuple[str, int]], width: int = _SKILLS_COLUMN_WIDTH) -> ft.Control:
    """検索結果一覧・回収一覧のスキル内訳セルを組み立てる。

    「名前＋値」を「、」区切りで並べて表示するが、単純に1つのft.Textへ連結すると、
    日本語テキストの行間はどこでも改行可能とみなされ、指定した幅で折り返す際に
    スキル名の途中で改行されてしまうことがある（例:「散弾」が「散」「弾」に分断される）。
    スキルごとに独立したft.Textとして並べ、ft.Row(wrap=True)で折り返すことで、
    スキルの区切り（「、」の直後）でしか改行されないようにする。
    """
    if not skills:
        return ft.Container(width=width)

    controls: list[ft.Control] = []
    for i, (name, value) in enumerate(skills):
        text = f"{name}{value:+d}"
        if i < len(skills) - 1:
            text += "、"
        controls.append(
            ft.Text(
                text,
                # マイナス値のスキルは目立つように赤字にする
                color=ft.Colors.RED if value < 0 else None,
            )
        )
    return ft.Row(controls, wrap=True, spacing=0, run_spacing=0, width=width)
