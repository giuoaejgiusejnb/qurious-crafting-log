"""EasyOCR で毎回スキル名だけを読み、kuijin_ocr.py の結果と照らし合わせる（検算用）。

kuijin_ocr.py とは独立した方法（画像ごとに OCR し、difflib でスキル一覧に補正）で読むので、
両者の食い違いを調べれば読み間違いを見つけられる。レベルは読まない。

使い方:
  # 1. OCR して結果を CSV に保存する（GPU があれば自動で使う）
  python scripts/ocr/check_skills_easyocr.py ocr samples/base_slot3/aaaa -o samples/base_slot3/aaaa_easyocr.csv
  # 2. kuijin_ocr.py の結果と比べ、食い違った画像を CSV に書き出す
  python scripts/ocr/check_skills_easyocr.py compare samples/base_slot3/aaaa_easyocr.csv samples/base_slot3/aaaa_result.csv -o mismatch.csv
"""

import argparse
import csv
import difflib
import sys
import time
from pathlib import Path

import cv2
import easyocr
import torch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))   # リポジトリ直下（app パッケージ）を import できるようにする

from app.core.skill_master import SKILL_MASTER  # noqa: E402

skill_master_list = [name for _, names in SKILL_MASTER for name in names]

NOT_FOUND = "該当なし"
ROI = (slice(361, 565), slice(540, 700))   # スキル欄（y, x）
CHUNK_SIZE = 12


def correct_skill_name(ocr_text, master_list):
    """
    OCRテキストをマスターリスト内の最も近いスキル名に補正します。
    """
    # get_close_matches: 最も似ている候補をリストで返す
    # 0.45は小さすぎるかも
    matches = difflib.get_close_matches(ocr_text, master_list, n=1, cutoff=0.45)
    if matches:
        # 最も似ている候補を返す
        return matches[0]
    else:
        # 適切な候補が見つからない場合は該当なしと返す
        return NOT_FOUND


def detect_skills_easyocr(image_paths, allowlist):
    """画像ごとに [画像パス, [スキル名, ...]] を返す（読めた文字列の順）。"""
    gpu = torch.cuda.is_available()
    print(f"GPU: {torch.cuda.get_device_name(0) if gpu else 'なし（CPU で実行）'}")
    # リーダーはループの前で 1 回だけ初期化
    reader = easyocr.Reader(["ja", "en"], gpu=gpu, verbose=False)
    image_skills_list = []
    total_images = len(image_paths)
    start = time.perf_counter()

    # まとめて読み込まず、必要な分だけその都度読み込む
    for i in range(0, total_images, CHUNK_SIZE):
        batch_paths = image_paths[i : i + CHUNK_SIZE]
        current_chunk_images, loaded_paths = [], []
        for p in batch_paths:
            img = cv2.imread(p)
            if img is not None:
                roi = cv2.resize(img[ROI], None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
                current_chunk_images.append(roi)
                loaded_paths.append(p)

        results_chunk = reader.readtext_batched(
            current_chunk_images,
            allowlist=allowlist,
            batch_size=4,
            detail=0,
            paragraph=False,
        )
        for path, results in zip(loaded_paths, results_chunk):
            skills = [correct_skill_name(text.strip(), skill_master_list) for text in results]
            image_skills_list.append([path, skills])

        if gpu:
            torch.cuda.empty_cache()   # VRAM の定期解放
        if i % 600 == 0:
            elapsed = time.perf_counter() - start
            print(f"OCR実行中... ({i}/{total_images})  {elapsed:.0f}s")

    return image_skills_list


def run_ocr(inputs, output):
    image_paths = []
    for item in inputs:
        p = Path(item)
        image_paths += sorted(str(f) for f in p.glob("*.jpg")) if p.is_dir() else [str(p)]
    unique_chars = "".join(sorted(set("".join(skill_master_list))))
    start = time.perf_counter()
    results = detect_skills_easyocr(image_paths, unique_chars)
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "skills"])
        for path, skills in results:
            writer.writerow([Path(path).name, "|".join(skills)])
    print(f"{len(results)} 枚, {time.perf_counter() - start:.0f}s -> {output}")


def run_compare(easyocr_csv, kuijin_csv, output):
    """画像ごとにスキル名の集まり（順不同、"該当なし" は除く）が一致するかを比べる。"""
    with open(easyocr_csv, encoding="utf-8-sig") as f:
        ocr = {r["file"]: {s for s in r["skills"].split("|") if s and s != NOT_FOUND} for r in csv.DictReader(f)}
    rows, counts = [], {"一致": 0, "食い違い": 0, "結果画面以外": 0, "EasyOCR側に無し": 0}
    with open(kuijin_csv, encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok" and r["status"] != "check":
                counts["結果画面以外"] += 1
                continue
            if r["file"] not in ocr:
                counts["EasyOCR側に無し"] += 1
                continue
            mine = {r[f"skill{i}"] for i in (1, 2, 3) if r[f"skill{i}"]}
            theirs = ocr[r["file"]]
            if mine == theirs:
                counts["一致"] += 1
            else:
                counts["食い違い"] += 1
                rows.append([r["file"], r["screen"], "|".join(sorted(mine - theirs)), "|".join(sorted(theirs - mine)),
                             "|".join(r[f"skill{i}"] for i in (1, 2, 3) if r[f"skill{i}"]), "|".join(sorted(theirs))])
    with open(output, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["file", "screen", "kuijinのみ", "easyocrのみ", "kuijin", "easyocr"])
        writer.writerows(rows)
    print(counts, "->", output)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("ocr", help="EasyOCR でスキル名を読んで CSV に保存する")
    p.add_argument("inputs", nargs="+", help="画像ファイルまたはフォルダ")
    p.add_argument("-o", "--output", required=True)
    p = sub.add_parser("compare", help="kuijin_ocr.py の結果と比べる")
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
