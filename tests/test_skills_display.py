from app.ui.skills_display import build_skills_wrap


def test_skills_are_ordered_like_the_game():
    """プラスをコストの高い順（同じコストはスキル一覧の順）→ マイナス → 写っていないスキルの印。"""
    row = build_skills_wrap([
        ("何らかのマイナススキル", 0), ("攻撃", -1), ("KO術", 1), ("ひるみ軽減", 1), ("見切り", 1),
        ("表記ゆれのスキル", 1), ("超会心", 2),
    ])
    assert [t.value.rstrip("、") for t in row.controls] == [
        "見切り+1", "超会心+2", "KO術+1", "ひるみ軽減+1", "表記ゆれのスキル+1", "攻撃-1", "何らかのマイナススキル",
    ]
