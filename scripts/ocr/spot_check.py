"""抜き取り確認用に、ランダムに選んだ画像の右側パネルと読み取り結果を並べた一覧画像を作る。

1 枚の一覧画像に 6 枚ずつ並べる。結果画面２・レア演出（赤く光った画面）は数が少ないので、
全体の約 1 割ずつ優先して混ぜる。一覧画像を見て、パネルと右の文字がすべて一致しているかを確かめる。

使い方:
  python scripts/ocr/spot_check.py samples/base_slot6/0925_1_result.csv samples/base_slot6/0925_1 -n 60 -o spot/0925_1
"""

import argparse
import csv
import random
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

PANEL = (slice(140, 550), slice(505, 775))   # 1280x720 の右側パネル（防御力〜スキル 3 つ目。結果画面２は 25 画素下がる）
FONT = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 15)
PER_SHEET = 6


def glow(img):
    """レア演出の赤さ（パネル内の R と G の平均の差）。"""
    p = img[PANEL].astype(int)
    return (p[..., 2] - p[..., 1]).mean()   # 通常の画面は 0 前後、レア演出は 10 以上


def tile(img, row):
    panel = cv2.cvtColor(img[PANEL], cv2.COLOR_BGR2RGB)
    h, w = panel.shape[:2]
    canvas = Image.new("RGB", (w + 240, h), (30, 30, 60))
    canvas.paste(Image.fromarray(panel), (0, 0))
    lines = [row["file"][:16], f"{row['status']} {row['screen']}",
             f"防御 {row['defense']}  スロット {row['slot_add']}",
             f"火{row['fire']} 水{row['water']} 雷{row['thunder']}",
             f"氷{row['ice']} 龍{row['dragon']}"]
    lines += [f"{row[f'skill{i}']} {row[f'lv{i}']}" for i in (1, 2, 3) if row[f"skill{i}"]]
    draw = ImageDraw.Draw(canvas)
    for n, text in enumerate(lines):
        draw.text((w + 8, 8 + n * 24), text, font=FONT, fill=(255, 255, 0))
    return np.array(canvas)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("detail_csv", help="kuijin_ocr.py --detail で出した CSV")
    parser.add_argument("image_dir")
    parser.add_argument("-n", type=int, default=60, help="確認する枚数（既定 60）")
    parser.add_argument("--seed", type=int, help="乱数の種（同じ画像を選び直したいとき）")
    parser.add_argument("-o", "--output", required=True, help="一覧画像を書き出すフォルダ")
    args = parser.parse_args()

    rng = random.Random(args.seed)
    with open(args.detail_csv, encoding="utf-8-sig") as f:
        rows = [r for r in csv.DictReader(f) if r["status"] in ("ok", "check")]
    extra = max(1, args.n // 10)
    screen2 = [r for r in rows if r["screen"] == "screen2"]
    picked = rng.sample(screen2, min(extra, len(screen2)))
    n_screen2 = len(picked)
    # レア演出は画像を見ないと分からないので、候補を多めに選んで赤いものを取る
    candidates = rng.sample(rows, min(len(rows), extra * 150))
    candidates.sort(key=lambda r: -glow(cv2.imread(str(Path(args.image_dir) / r["file"]))))
    picked += [r for r in candidates if r not in picked][:extra]
    rest = [r for r in rows if r not in picked]
    picked += rng.sample(rest, min(args.n - len(picked), len(rest)))

    out = Path(args.output)
    out.mkdir(parents=True, exist_ok=True)
    tiles = [tile(cv2.imread(str(Path(args.image_dir) / r["file"])), r) for r in picked]
    for s in range(0, len(tiles), PER_SHEET):
        group = tiles[s:s + PER_SHEET]
        group += [np.zeros_like(group[0])] * (PER_SHEET - len(group))
        sheet = np.vstack([np.hstack(group[:3]), np.hstack(group[3:])])
        Image.fromarray(sheet).save(out / f"spot_{s // PER_SHEET:02d}.png")
    with open(out / "files.txt", "w", encoding="utf-8") as f:
        f.write("".join(r["file"] + "\n" for r in picked))
    print(f"{len(picked)} 枚（結果画面２ {n_screen2} 枚・レア演出 {extra} 枚を含む）"
          f" -> {out}（一覧画像 {(len(tiles) + PER_SHEET - 1) // PER_SHEET} 枚）")


if __name__ == "__main__":
    main()
