"""kuijin_ocr.py の詳しい結果（--detail の CSV）から、指定したスキルのどれかのレベルが
一定以上上がった画像だけを選び、フォルダにコピーする。あわせて、選んだ画像の一覧
（ファイル名と該当スキル）を「コピー先フォルダ名.txt」に書く。

スキル名は【】の有無を区別しない（"業鎧修羅" でも "業鎧【修羅】" に一致する）。

使い方:
  python scripts/ocr/pick_images.py samples/base_slot6/switch2_result.csv samples/base_slot6/switch2 \\
      -s 龍気変換 奮闘 激昂 業鎧修羅 狂竜症蝕 -o picked
"""

import argparse
import csv
import shutil
import sys
from pathlib import Path

import sys
from pathlib import Path as _Path

sys.path.insert(0, str(_Path(__file__).resolve().parents[2]))   # リポジトリ直下（app パッケージ）を import できるようにする

from app.core.skill_master import ALL_MASTER_SKILL_NAMES


def normalize(name: str) -> str:
    return name.replace("【", "").replace("】", "").replace(" ", "")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detail_csv", help="kuijin_ocr.py --detail で出した CSV")
    parser.add_argument("image_dir", help="その CSV を作ったときの画像フォルダ")
    parser.add_argument("-s", "--skills", nargs="+", required=True, help="対象のスキル名")
    parser.add_argument("--min-level", type=int, default=1, help="この値以上レベルが上がったものを選ぶ（既定 1）")
    parser.add_argument("-o", "--output", required=True, help="コピー先のフォルダ")
    args = parser.parse_args()

    known = {normalize(n): n for n in ALL_MASTER_SKILL_NAMES}
    targets = set()
    for s in args.skills:
        if normalize(s) not in known:
            sys.exit(f"スキル名 {s!r} が skill_master.py にありません")
        targets.add(normalize(s))

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    picked, unreadable, listing = 0, 0, []
    with open(args.detail_csv, encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["status"] not in ("ok", "check"):
                continue
            hits = []
            for i in (1, 2, 3):
                name, lv = row[f"skill{i}"], row[f"lv{i}"]
                if not name or normalize(name.rstrip("?")) not in targets:
                    continue
                if "?" in lv or "?" in name:
                    unreadable += 1
                    continue
                if int(lv) >= args.min_level:
                    hits.append(f"{name}{lv}")
            if hits:
                listing.append(f"{row['file']},{' '.join(hits)}")
                shutil.copy2(Path(args.image_dir) / row["file"], out / row["file"])
                picked += 1
    list_path = out.with_name(out.name + ".txt")
    list_path.write_text("".join(line + "\n" for line in listing), encoding="utf-8")
    print(f"一覧 -> {list_path}")
    print(f"{picked} 枚を {out} にコピーしました（対象: {', '.join(known[t] for t in sorted(targets))}）")
    if unreadable:
        print(f"注意: 対象スキルのうち名前かレベルが読めていないものが {unreadable} 件あり、選んでいません")


if __name__ == "__main__":
    main()
