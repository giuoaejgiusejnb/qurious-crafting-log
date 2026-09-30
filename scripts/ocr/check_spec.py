"""読み取り結果が傀異錬成の抽選の仕様で作れる結果かを調べる（検算用）。

判定はアプリの取込時と同じ app/ocr/spec.py を使う（仕様と、防御力の値を判定に使わない理由はそちらを参照）。
スキルがすべて写っている結果画面１だけを調べる。

使い方:
  python scripts/ocr/check_spec.py --table 5 --minus-skills 攻撃:2,火事場力:3 \\
      samples/base_slot6/0925_1_result.csv -o samples/base_slot6/0925_1_spec_errors.csv
"""

import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # リポジトリ直下（app パッケージ）を import できるようにする

from app.ocr.kuijin_ocr import parse_minus_skills  # noqa: E402
from app.ocr.spec import RESISTS, TABLES, SpecChecker  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detail_csv", nargs="+", help="kuijin_ocr の --detail で出した CSV")
    parser.add_argument("--table", type=int, required=True, choices=sorted(TABLES),
                        help="防具の抽選テーブル（マッスル = 5、ギルパレ・クシャ = 6）")
    parser.add_argument("--minus-skills", metavar="スキル:元のLv,…",
                        help="防具が元から持つスキル（例: 攻撃:2,火事場力:3）。指定するとスキルの種類の上限も調べる")
    parser.add_argument("-o", "--output", required=True)
    args = parser.parse_args()

    checker = SpecChecker(args.table, parse_minus_skills(args.minus_skills or ""))
    counts = {"OK": 0, "仕様違反": 0, "判定外": 0}
    out = []
    for path in args.detail_csv:
        with open(path, encoding="utf-8-sig") as f:
            for row in csv.DictReader(f):
                if row["status"] not in ("ok", "check"):
                    continue
                if row["screen"] != "screen1":
                    counts["判定外"] += 1
                    continue
                reason = checker.violation(row)
                if reason is None:
                    counts["OK"] += 1
                    continue
                counts["仕様違反"] += 1
                out.append([path, row["file"], reason, row["defense"], row["slot_add"],
                            *(row[x] for x in RESISTS),
                            *(f"{row[f'skill{i}']}{row[f'lv{i}']}" for i in (1, 2, 3))])
    with open(args.output, "w", newline="", encoding="utf-8-sig") as f:
        w = csv.writer(f)
        w.writerow(["csv", "file", "理由", "防御", "スロ", *RESISTS, "スキル1", "スキル2", "スキル3"])
        w.writerows(out)
    print(counts, "->", args.output)


if __name__ == "__main__":
    main()
