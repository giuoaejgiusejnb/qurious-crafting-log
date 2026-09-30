"""読み取り結果が傀異錬成の抽選仕様（hyperWiki のテーブル）で作れる結果かを調べる（検算用）。

仕様:
  - 基礎コストはテーブルで決まる（テーブル 5 = 12、テーブル 6 = 10）
  - 抽選は最大 6 回。1 回ごとに 1 項目を引き、そのコストを使う（同じカテゴリが何度出てもよい）
  - コストがマイナスの項目は、その分コストが増える。使ったコストの合計は基礎コスト以下
    （マイナスの項目を先に引いたとみなせるので、順番は考えなくてよい）
  - 最後に必ず、残ったコストを防御力に変換する（特別枠）。残りコスト以下でコストが最大の
    防御力の項目を 1 つ付ける（確率 0 の項目も含む）。使い切れなかったコストは捨てる。
    例: テーブル 6 で残り 1, 2 → +1、3, 4 → +2（ユーザーの観察と一致）。この規則はデータから推定したもの。
    2026-09 時点で、テーブル 5（マッスル）23,329 枚は全件説明できる。テーブル 6（ギルドパレス）は
    9,964 枚中 31 枚が説明できず、変換の規則に未解明の部分がある（読み取りは目視で正しいと確認済み）
  - 属性耐性は 5 属性のどれかにランダムに付く（同じ属性に何度付いてもよい）
  - スキルは、そのスキルのコストの項目を引くと +1。コスト -10 の項目で既存スキルが -1
  - 確率 0 の項目（最後の変換枠を除く）と「不明」の項目は引かれないものとして扱う
画像 1 枚ごとに、仕様を満たす引き方が 1 つでもあれば OK、無ければ仕様違反として出力する。

使い方:
  python scripts/ocr/check_spec.py --table 5 samples/base_slot6/0925_1_result.csv -o samples/base_slot6/0925_1_spec_errors.csv
"""

import argparse
import csv
from functools import lru_cache
from itertools import product

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))   # リポジトリ直下（app パッケージ）を import できるようにする

from app.core.skill_master import SKILL_MASTER

TABLES = {
    # テーブル番号: (基礎コスト, 防御力の項目 [(コスト, 取りうる値)], 属性耐性の項目, スロットの項目,
    #                最後の変換枠で使う防御力の項目（確率 0 の項目を含む）)
    5: (12,
        [(12, (12, 14, 16)), (9, (10, 11, 12)), (6, (6, 7, 8)), (5, (4, 5, 6)), (1, (1,)), (-3, (-6,)), (-5, (-12,))],
        [(2, (1, 2)), (-2, (-1, -2)), (-3, (-3,))],
        [(6, 1), (12, 2), (18, 3)],
        [(12, (12, 14, 16)), (9, (10, 11, 12)), (6, (6, 7, 8)), (5, (4, 5, 6)), (4, (4,)), (3, (3,)), (2, (2,)), (1, (1,))]),
    6: (10,
        [(10, (8, 10, 12)), (7, (6, 7, 8)), (5, (4, 5, 6)), (1, (1,)), (-3, (-6,)), (-5, (-12,))],
        [(2, (1, 2)), (-2, (-1, -2)), (-3, (-3,))],
        [(6, 1), (12, 2), (18, 3)],
        [(10, (8, 10, 12)), (7, (6, 7, 8)), (5, (4, 5, 6)), (4, (2,)), (3, (2,)), (2, (1,)), (1, (1,))]),
}
MAX_DRAWS = 6
SKILL_COST = {name: cost for cost, names in SKILL_MASTER for name in names}
SKILL_DOWN_COST = -10
RESISTS = ["fire", "water", "thunder", "ice", "dragon"]


def build(table):
    base, defense_items, resist_items, slot_items, convert_items = TABLES[table]

    def convert(rest):
        """最後の枠で付く防御力の候補。"""
        for cost, vals in convert_items:
            if cost <= rest:
                return vals
        return (0,)

    # 1 属性の合計 t を作る引き方: (回数, コスト) の集合
    resist_draws = [(c, v) for c, vals in resist_items for v in vals]

    @lru_cache(maxsize=None)
    def resist_ways(t, n_left):
        ways = {(0, 0)} if t == 0 else set()
        if n_left == 0:
            return frozenset(ways)
        for c, v in resist_draws:
            for n, cost in resist_ways(t - v, n_left - 1):
                ways.add((n + 1, cost + c))
        return frozenset(ways)

    # 防御力の引き方: (回数, コスト) -> 取りうる合計の集合
    defense_ways = {(0, 0): {0}}
    for _ in range(MAX_DRAWS):
        nxt = {k: set(v) for k, v in defense_ways.items()}
        for (n, cost), sums in defense_ways.items():
            if n >= MAX_DRAWS:
                continue
            for c, vals in defense_items:
                key = (n + 1, cost + c)
                nxt.setdefault(key, set()).update(s + v for s in sums for v in vals)
        defense_ways = nxt

    # スロット追加数 s を作る引き方: (回数, コスト) の集合
    slot_ways = {0: {(0, 0)}}
    for s in range(1, 3 * MAX_DRAWS + 1):
        slot_ways[s] = {(n + 1, cost + c) for c, v in slot_items if v <= s for n, cost in slot_ways[s - v]}

    return base, resist_ways, defense_ways, slot_ways, convert


def feasible(row, built):
    """仕様で作れるなら None、作れないなら理由の文字列。判定できない行は "skip"。"""
    base, resist_ways, defense_ways, slot_ways, convert = built
    if row["screen"] == "screen2":
        return "skip"   # 4 つ目以降のスキルが写っていない
    vals = [row["defense"], row["slot_add"], *(row[r] for r in RESISTS)]
    if any("?" in v for v in vals):
        return "skip"
    # スキル: 回数とコストは決まる
    n_fixed, cost_fixed = 0, 0
    for i in (1, 2, 3):
        name, lv = row[f"skill{i}"], row[f"lv{i}"]
        if not name:
            continue
        if "?" in name + lv or name not in SKILL_COST:
            return "skip"
        lv = int(lv)
        n_fixed += abs(lv)
        cost_fixed += lv * SKILL_COST[name] if lv > 0 else -lv * SKILL_DOWN_COST
    if n_fixed > MAX_DRAWS:
        return f"スキルだけで抽選 {n_fixed} 回分（最大 {MAX_DRAWS} 回）"
    slot = int(row["slot_add"])
    defense = 0 if row["defense"] == "-" else int(row["defense"])
    resists = [0 if row[r] == "-" else int(row[r]) for r in RESISTS]

    # 耐性 5 属性をまとめた引き方
    combos = {(0, 0)}
    for t in resists:
        ways = resist_ways(t, MAX_DRAWS)
        combos = {(n1 + n2, c1 + c2) for n1, c1 in combos for n2, c2 in ways if n1 + n2 <= MAX_DRAWS}
        if not combos:
            return "耐性の値が抽選の値の組み合わせで作れない"
    reasons = set()
    for (ns, cs), (nr, cr) in product(slot_ways.get(slot, set()), combos):
        n_left = MAX_DRAWS - n_fixed - ns - nr
        if n_left < 0:
            reasons.add("抽選回数が 6 回を超える")
            continue
        for (nd, cd), sums in defense_ways.items():
            if nd > n_left:
                continue
            rest = base - (cost_fixed + cs + cr + cd)
            if rest < 0:
                reasons.add("コストが足りない")
                continue
            if any(defense - v in sums for v in convert(rest)):
                return None
            reasons.add("防御力が合わない")
    return " / ".join(sorted(reasons)) or "スロットの値が作れない"


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detail_csv", nargs="+", help="kuijin_ocr.py --detail で出した CSV")
    parser.add_argument("--table", type=int, required=True, choices=sorted(TABLES),
                        help="防具の抽選テーブル（マッスル = 5、それ以外は今のところ 6）")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    built = build(args.table)
    counts = {"OK": 0, "仕様違反": 0, "判定外": 0}
    out = []
    for path in args.detail_csv:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["status"] not in ("ok", "check"):
                    continue
                r = feasible(row, built)
                if r is None:
                    counts["OK"] += 1
                elif r == "skip":
                    counts["判定外"] += 1
                else:
                    counts["仕様違反"] += 1
                    out.append([path, row["file"], r, row["defense"], row["slot_add"],
                                *(row[x] for x in RESISTS),
                                *(f"{row[f'skill{i}']}{row[f'lv{i}']}" for i in (1, 2, 3))])
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["csv", "file", "理由", "防御", "スロ", *RESISTS, "スキル1", "スキル2", "スキル3"])
        w.writerows(out)
    print(counts, "->", args.output)


if __name__ == "__main__":
    main()
