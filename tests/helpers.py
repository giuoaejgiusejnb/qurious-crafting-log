"""テスト用のresult_log行組み立てヘルパー。

実際のCSV列構成: 回数,ゼニー,スロ,コスト,マイナス,耐性,
第1名,第1値,...,第6名,第6値,対象
"""

_SKILL_SLOT_COUNT = 6

HEADER_LINE = (
    "回数,ゼニー,スロ,コスト,マイナス,耐性,"
    "第1名,第1値,第2名,第2値,第3名,第3値,第4名,第4値,第5名,第5値,第6名,第6値,対象"
)


def build_row(
    zeny_count: int = 1,
    zeny: int = 1,
    slot_add: int = 0,
    total_cost: int = 0,
    deficiency: str = "無",
    resistance: int = 0,
    skills: list[tuple[str, int]] | tuple[tuple[str, int], ...] = (),
) -> str:
    """テスト用のresult_log CSV行を1行組み立てる。"""
    skill_fields: list[str] = []
    for name, value in skills:
        skill_fields.extend([name, str(value)])
    if len(skill_fields) > _SKILL_SLOT_COUNT * 2:
        raise ValueError(f"skills must have at most {_SKILL_SLOT_COUNT} entries")
    while len(skill_fields) < _SKILL_SLOT_COUNT * 2:
        skill_fields.append("")

    fields = [
        str(zeny_count),
        str(zeny),
        str(slot_add),
        str(total_cost),
        deficiency,
        str(resistance),
        *skill_fields,
        "0",  # 対象列（未使用）
    ]
    return ",".join(fields)


def build_block(rows: list[str], initial_zeny: int = 9999) -> str:
    """先頭に「初期ゼニー」行と見出し行を付けたブロックを組み立てる。"""
    lines = [f"初期ゼニー,{initial_zeny}", HEADER_LINE, *rows]
    return "\n".join(lines)
