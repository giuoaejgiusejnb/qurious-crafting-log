"""EasyOCR で防御力・火〜龍耐性・スキルレベル・ゼニーを読み、kuijin_ocr.py の結果と照らし合わせる（検算用）。

kuijin_ocr.py とは別の方法で読む:
  - 数字は EasyOCR（文字の位置は決まっているので、検出は省いて認識だけ行う）
  - 符号は文字の色で決める（緑・オレンジ = +、赤 = -、灰色の "-" = 変化なし）。
    EasyOCR は "-" を読み落としやすいため
  - スキルレベルは "Lv +1" の文字を読む（kuijin_ocr.py は四角の色を数えている）
スキル名は check_skills_easyocr.py、スロットは対象外。

使い方:
  python scripts/ocr/check_values_easyocr.py ocr samples/base_slot6/switch2 -o samples/base_slot6/switch2_values_easyocr.csv
  python scripts/ocr/check_values_easyocr.py compare samples/base_slot6/switch2_values_easyocr.csv samples/base_slot6/switch2_result.csv -o mismatch.csv
"""

import argparse
import csv
import re
import time
from pathlib import Path

import cv2
import easyocr
import numpy as np
import torch

SCALE = 3                      # 認識前に拡大する倍率
PAGER = (slice(156, 178), slice(570, 612))   # 結果画面２の「◀ L 1/2 R ▶」
PAGER_DY = 25                  # 結果画面２では下の項目が 25 画素下がる
FIELDS = {                     # 名前: (x0, y0, x1, y1)。1280x720 基準、結果画面１の位置
    "defense": (700, 157, 764, 180),
    **{name: (700, y, 764, y + 22) for name, y in
       zip(["fire", "water", "thunder", "ice", "dragon"], [207, 231, 256, 281, 303])},
    **{f"lv{i + 1}": (686, 390 + dy, 764, 416 + dy) for i, dy in enumerate([0, 51, 101])},
}
MONEY = (1140, 16, 1228, 46)     # 左端はコインのアイコンの右端（約 1137）より右にする
CHUNK_SIZE = 32


def text_sign(img, box):
    """文字の色から符号を返す。"+" / "-" / "gray"（変化なし）/ ""（文字なし）。"""
    x0, y0, x1, y1 = box
    crop = img[y0:y1, x0:x1].astype(int)
    ink = crop.max(axis=2) > 150
    if ink.sum() < 8:
        gray = (crop.max(axis=2) > 70) & (crop.max(axis=2) - crop.min(axis=2) < 25)
        return "gray" if gray.sum() >= 4 else ""
    b, g, r = (crop[..., i][ink].mean() for i in range(3))
    if g > r + 40:
        return "+"
    if r > 150 and g > 100:       # オレンジ（最大レベルに達したとき）
        return "+"
    if r > g + 40:
        return "-"
    return "gray"


def read_image(reader, img):
    """1 枚分の値を dict で返す。読めない値は "?"。"""
    dy = PAGER_DY if (img[PAGER].min(axis=2) > 150).sum() > 200 else 0
    boxes = {name: (x0, y0 + dy, x1, y1 + dy) for name, (x0, y0, x1, y1) in FIELDS.items()}
    boxes["money"] = MONEY
    # 灰色化すると赤い文字が暗くなるので、RGB の最大値を明るさとして使う
    big = cv2.resize(img.max(axis=2), None, fx=SCALE, fy=SCALE, interpolation=cv2.INTER_CUBIC)
    names = list(boxes)
    hl = [[x0 * SCALE, x1 * SCALE, y0 * SCALE, y1 * SCALE] for x0, y0, x1, y1 in boxes.values()]
    # 枠を 1 つずつ渡す（まとめて渡すと結果の順番が枠の順と一致する保証がない）
    texts = {}
    for name, h in zip(names, hl):
        res = reader.recognize(big, horizontal_list=[h], free_list=[], detail=0, allowlist="0123456789+-Lv")
        texts[name] = "".join(res)
    out = {}
    for name in names:
        # 符号や "Lv" も読ませたうえで（読ませないと "+" を "4" と読む）、最後の数字の並びだけを使う
        found = re.findall(r"\d+", texts.get(name, ""))
        digits = found[-1] if found else ""
        if name == "money":
            out["money_k"] = digits[:-3] if len(digits) > 3 else "?"
            continue
        sign = text_sign(img, boxes[name])
        if name.startswith("lv"):
            # "Lv" の後ろの数字だけを見る（"Lv" は allowlist に無いので読まれない）。"なし" は数字なし・赤
            if sign == "":
                out[name] = ""
            elif sign == "-" and not digits:
                out[name] = "なし"
            else:
                out[name] = f"{sign}{digits}" if digits and sign in "+-" else "?"
        else:
            if sign in ("gray", ""):
                out[name] = "-"
            else:
                out[name] = f"{sign}{digits}" if digits else "?"
    out["screen"] = "screen2" if dy else "screen1"
    return out


def run_ocr(inputs, output):
    paths = []
    for item in inputs:
        p = Path(item)
        paths += sorted(str(f) for f in p.glob("*.jpg")) if p.is_dir() else [str(p)]
    gpu = torch.cuda.is_available()
    print(f"GPU: {torch.cuda.get_device_name(0) if gpu else 'なし（CPU で実行）'}")
    reader = easyocr.Reader(["en"], gpu=gpu, verbose=False)
    cols = ["file", "screen", *FIELDS, "money_k"]
    start = time.perf_counter()
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=cols)
        writer.writeheader()
        for i, path in enumerate(paths):
            img = cv2.imread(path)
            if img is None:
                continue
            if img.shape[:2] != (720, 1280):
                img = cv2.resize(img, (1280, 720), interpolation=cv2.INTER_AREA)
            writer.writerow({"file": Path(path).name, **read_image(reader, img)})
            if i % 1000 == 0:
                print(f"OCR実行中... ({i}/{len(paths)})  {time.perf_counter() - start:.0f}s")
    print(f"{len(paths)} 枚, {time.perf_counter() - start:.0f}s -> {output}")


def same(field, mine, theirs):
    """kuijin_ocr.py の値 mine と EasyOCR の値 theirs が同じとみなせるか。"""
    if field.startswith("lv"):
        if theirs == "なし":            # スキルが消えた。kuijin 側は減ったレベル（-1 以下）
            return mine.startswith("-")
        if mine and theirs:
            return int(mine) == int(theirs) if "?" not in mine + theirs else False
    return mine == theirs


NEEDS_REVIEW = "要確認"


def is_subsequence(short, long):
    it = iter(long)
    return all(ch in it for ch in short)


def classify(field, mine, theirs):
    """食い違いを、これまでの確認で EasyOCR 側の誤りと分かっている形に分類する。

    自動で分類するのは、符号が同じで数字の並びが包含関係にある（桁の読み増し・読み落とし）など、
    EasyOCR の誤り方がはっきりしているものだけ。符号が違う・数字が別物などは NEEDS_REVIEW。
    """
    if field.startswith("lv"):
        if mine == "":
            return "スキルの無い行で演出の粒を読んだ"
        if mine.startswith("-") and theirs in ("-1", "なし") and int(mine) <= -1:
            return "「なし」を数字と読んだ"   # 減った量は EasyOCR では分からない
        return NEEDS_REVIEW
    if theirs == "?":
        return "数字を読み落とした"
    if field == "money_k":   # ゼニーは符号が無い。先頭に数字を足す・同じ数字の並びを読み落とすことが多い
        if mine != theirs and (is_subsequence(mine, theirs) or is_subsequence(theirs, mine)):
            return "桁の読み増し・読み落とし"
        return NEEDS_REVIEW
    if mine == "-":
        return "灰色の「-」の近くの演出の粒を読んだ"
    if mine[:1] != theirs[:1] or mine[:1] not in "+-":
        return NEEDS_REVIEW
    a, b = mine[1:], theirs[1:]
    if a != b and (is_subsequence(a, b) or is_subsequence(b, a)):
        return "桁の読み増し・読み落とし"
    return NEEDS_REVIEW


def run_compare(easy_csv, kuijin_csv, output):
    with open(easy_csv, encoding="utf-8-sig") as f:
        easy = {r["file"]: r for r in csv.DictReader(f)}
    fields = [*FIELDS, "money_k"]
    rows, total, kinds, bad_imgs = [], {k: 0 for k in fields}, {}, set()
    with open(kuijin_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["status"] not in ("ok", "check") or r["file"] not in easy:
                continue
            e = easy[r["file"]]
            for k in fields:
                if not same(k, r[k], e[k]):
                    kind = classify(k, r[k], e[k])
                    total[k] += 1
                    kinds[kind] = kinds.get(kind, 0) + 1
                    bad_imgs.add(r["file"])
                    rows.append([kind, r["file"], r["screen"], k, r[k], e[k]])
    rows.sort(key=lambda x: x[0] != NEEDS_REVIEW)   # 要確認を先頭に
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["分類", "file", "screen", "項目", "kuijin", "easyocr"])
        writer.writerows(rows)
    print(f"食い違い {len(rows)} 件（画像 {len(bad_imgs)} 枚） 項目別 {total} -> {output}")
    for kind, n in sorted(kinds.items(), key=lambda x: (x[0] != NEEDS_REVIEW, -x[1])):
        print(f"  {kind}: {n}")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ocr", help="EasyOCR で値を読んで CSV に保存する")
    p.add_argument("inputs", nargs="+", help="画像ファイルまたはフォルダ")
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("compare", help="kuijin_ocr.py の --detail の CSV と比べる")
    p.add_argument("easyocr_csv")
    p.add_argument("kuijin_csv")
    p.add_argument("-o", "--output", required=True)
    args = parser.parse_args()
    if args.command == "ocr":
        run_ocr(args.inputs, args.output)
    else:
        run_compare(args.easyocr_csv, args.kuijin_csv, args.output)


if __name__ == "__main__":
    main()
