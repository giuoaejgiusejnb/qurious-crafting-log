"""実際のユーザーによる貼り付けを想定した、大量サンプルのresult_logテキストを生成する。

生成したテキストは、アプリの取込タブにそのまま貼り付けて手動テストできる。

観察された実データの規則性（100行サンプルより）:
- ゼニーは1回あたり常に一定量（既定4）ずつ減少する
- 「コスト」列は「スロ×6 + プラス値のスキルのコスト合計」（マイナス値のスキルは
  コストに含まれない）。コストはスキルマスター（skill_master.py）のコスト階層を参照する
- プラス値は常に+1、マイナス値は常に-1
- 「マイナス」フラグ（無/有）は、含まれるスキルに1つでもマイナス値があるときだけ「有」

使い方:
    .venv/Scripts/python.exe scripts/generate_sample_paste.py 25000 --out sample_paste_25000.txt
"""

import argparse
import random
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.skill_master import SKILL_MASTER  # noqa: E402

SKILL_COST: dict[str, int] = {name: cost for cost, names in SKILL_MASTER for name in names}
ALL_SKILL_NAMES: list[str] = list(SKILL_COST.keys())

HEADER_LINE = (
    "回数,ゼニー,スロ,コスト,マイナス,耐性,"
    "第1名,第1値,第2名,第2値,第3名,第3値,第4名,第4値,第5名,第5値,第6名,第6値,対象"
)

INITIAL_ZENY = 4936
ZENY_STEP = 4  # 実サンプルの観察上、1回あたり4ずつ減少する
SLOT_COST_PER_LEVEL = 6


def _choose_skill_count(rng: random.Random) -> int:
    return rng.choices([0, 1, 2, 3, 4], weights=[20, 50, 20, 7, 3])[0]


def _choose_slot_add(rng: random.Random) -> int:
    return rng.choices([0, 1, 2], weights=[80, 15, 5])[0]


def _generate_row(rng: random.Random, count: int) -> str:
    zeny = INITIAL_ZENY - ZENY_STEP * count
    slot_add = _choose_slot_add(rng)

    skill_count = _choose_skill_count(rng)
    names = rng.sample(ALL_SKILL_NAMES, k=skill_count) if skill_count else []

    has_deficiency = skill_count > 0 and rng.random() < 0.15
    deficiency_index = rng.randrange(skill_count) if has_deficiency else -1

    skills: list[tuple[str, int]] = [
        (name, -1 if i == deficiency_index else 1) for i, name in enumerate(names)
    ]

    total_cost = slot_add * SLOT_COST_PER_LEVEL + sum(
        SKILL_COST[name] for name, value in skills if value > 0
    )
    resistance = rng.randint(-7, 4)

    skill_fields: list[str] = []
    for name, value in skills:
        skill_fields.extend([name, str(value)])
    while len(skill_fields) < 12:
        skill_fields.append("")

    fields = [
        str(count),
        str(zeny),
        str(slot_add),
        str(total_cost),
        "有" if has_deficiency else "無",
        str(resistance),
        *skill_fields,
        "0",  # 対象列（未使用）
    ]
    return ",".join(fields)


def generate_block(row_count: int, seed: int = 42) -> str:
    rng = random.Random(seed)
    lines = [f"初期ゼニー,{INITIAL_ZENY}", HEADER_LINE]
    lines.extend(_generate_row(rng, i) for i in range(1, row_count + 1))
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="実際の貼り付けを想定したサンプルデータを生成する")
    parser.add_argument("row_count", type=int, nargs="?", default=25000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--out", type=str, default=None)
    args = parser.parse_args()

    text = generate_block(args.row_count, seed=args.seed)

    out_path = Path(args.out) if args.out else Path(f"sample_paste_{args.row_count}.txt")
    out_path.write_text(text, encoding="utf-8")
    print(f"生成完了: {out_path} ({args.row_count}行)")


if __name__ == "__main__":
    main()
