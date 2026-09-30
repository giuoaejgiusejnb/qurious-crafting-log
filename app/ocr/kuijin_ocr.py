"""傀異錬成結果画面のスクリーンショットから、強化後のステータスを高速に読み取る。

読み取る項目:
  防御力 / スロット / 火〜龍耐性 / スキル名とレベルの増減（最大 3 つ）
  あわせてコスト（6 × 追加スロット数 + レベルが上がったスキルのコスト × 上がったレベル）を出す

方針:
  各項目は固定フォント・固定位置で描画されるため、同じ値の切り出し画像はほぼ
  同一のピクセルになる。そこで
    1. 画面の種類を判定し、各項目を切り出して二値化（マルチプロセス）
    2. 既知テンプレートと照合し、一致しないものだけ新しいテンプレートにする
    3. 新しいテンプレートにラベルを付ける
         スキル名: EasyOCR で読み、skill_master の最も近い名前に補正
         数値    : 符号は形で判定し、数字は 1 文字ずつ数字テンプレートと照合
                   （EasyOCR は "-" や 1 桁の数字を読み落とすため）
         スロット・符号と数字: 種類が少ないので templates/*.json を手で編集して名前を付ける
                   （スロットは追加数 "+0"〜"+6"。追加部分の見た目は初期スロットごとに違うので、
                    テンプレートは実行時に --base-slot で指定した初期スロットごとに分けて持つ）
    4. テンプレートを templates/ に保存し、次回以降は照合だけで済ませる
  スキルのレベルの増減は "Lv +1" の文字ではなく、スキル名の下の四角の色を数えて求める
  （緑 1 個 = +1、赤 1 個 = -1）。"なし"（スキルが消えた）のときも減った量が分かる。

  テンプレートは本体ごと（解像度ごと）に分けて持つ。画像は 1280x720 に
  そろえてから処理するので、座標は 1 組で共通。
  レア演出（画面が赤く光る）や HDR の明るさ変化に備え、二値化は切り出し範囲の
  背景（中央値）との差で行う。

使い方（リポジトリ直下で実行）:
  python -m app.ocr.kuijin_ocr --base-slot 3 --zenny-step 4000 samples/base_slot3/aaaa -o result.txt
  （--detail detail.csv を付けると、1 枚ごとの詳しい読み取り結果も CSV で出す）
  python -m app.ocr.kuijin_ocr --base-slot 6 samples/base_slot6/switch2 --slot-sheet slot_check.png   # スロットの名前を目で確認する
  python -m app.ocr.kuijin_ocr --save-signature screen1 <結果画面の画像>   # 画面判定用の見本を作る

アプリ（取込タブの「画像から取込」）からは read_images() を呼ぶ。
"""

from __future__ import annotations

import argparse
import csv
import difflib
import json
import os
import shutil
import sys
import time
import unicodedata
from concurrent.futures import Executor, ProcessPoolExecutor, ThreadPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

from app.core.skill_master import ALL_MASTER_SKILL_NAMES, SKILL_MASTER, UNKNOWN_SKILL_NAME

BASE_SIZE = (1280, 720)   # (幅, 高さ) この大きさにそろえてから処理する
# 同梱の見本（確認済みのテンプレート）。CLI は既定でここを読み書きする。
# アプリはインストール先に書き込めないため、user_template_dir() で作業用の複製を使う
BUNDLED_TEMPLATE_DIR = Path(__file__).with_name("templates")

# 同一テンプレートとみなす条件: 全体の 1 - IoU と、文字 1 つ分（BLOCK_W 幅）ごとの 1 - IoU の最大値
# （全体だけだと「火属性攻撃強化」と「氷属性攻撃強化」のような 1 文字違いが一致してしまう）
MATCH_THRESHOLD = {"default": (0.15, 0.2),
                   # 二値化した「雷」と「龍」は、別の行の「龍」同士より近いことがあるため、
                   # スキル名はほぼ完全一致のときだけまとめ、見分けは OCR に任せる
                   "name": (0.03, 0.15),
                   "glyph": (0.15, 1.0),   # 1 文字ずつなので全体の IoU だけ
                   "money_glyph": (0.15, 1.0)}
BLOCK_W = 16
SIGNATURE_THRESHOLD = 0.3
AMBIGUOUS_MARGIN = 0.1    # スキル名の補正で、1 位と 2 位の類似度の差がこれ未満なら要確認
MIN_INK = 40              # スキル名行の画素数がこれ未満ならスキル無し
MIN_CONTRAST = 30         # 割合で決めるしきい値の下限（何も書かれていない欄でノイズを拾わないため）
DIGIT_SHAPE = (20, 14)    # 数値の 1 文字（符号・数字）の切り出しサイズ


@dataclass(frozen=True)
class Region:
    x0: int
    y0: int
    x1: int
    y1: int
    channel: str      # "min": 白文字用 / "max": 色付き文字用 / "gb": 灰色・緑のアイコン用（赤い演出光を無視）
    contrast: float   # 背景との差がこれ以上なら文字とみなす。1 未満なら「最も明るい画素と背景の差」に対する割合
    min_component: int = 3    # これ未満の画素数の点はノイズ（JPEG ノイズ・演出のきらめき）として捨てる

    @property
    def shape(self) -> tuple[int, int]:
        return self.y1 - self.y0, self.x1 - self.x0

    def threshold(self, img: np.ndarray, dy: int = 0) -> np.ndarray:
        """切り出し範囲を背景との差で二値化する（位置はそろえない）。"""
        crop = img[self.y0 + dy:self.y1 + dy, self.x0:self.x1]
        if self.channel == "min":
            ch = crop.min(axis=2)
        elif self.channel == "gb":
            ch = crop[..., :2].max(axis=2)   # BGR の B と G
        else:
            ch = crop.max(axis=2)
        diff = ch.astype(np.int16) - int(np.median(ch))
        thr = self.contrast if self.contrast >= 1 else max(self.contrast * diff.max(), MIN_CONTRAST)
        return diff > thr

    def binarize(self, img: np.ndarray, dy: int = 0) -> np.ndarray:
        return align(self.threshold(img, dy), self.min_component)


def _keep_components(ink: np.ndarray, min_component: int) -> np.ndarray:
    n, labels, stats, _ = cv2.connectedComponentsWithStats(ink.astype(np.uint8), connectivity=8)
    return np.isin(labels, [i for i in range(1, n) if stats[i, cv2.CC_STAT_AREA] >= min_component])


def align_offset(ink: np.ndarray, min_component: int) -> tuple[int, int]:
    """align で左上にそろえるときのずらし量 (y, x)。文字が無ければ (0, 0)。"""
    ys, xs = np.nonzero(_keep_components(ink, min_component))
    return (int(ys.min()), int(xs.min())) if len(ys) else (0, 0)


def align(ink: np.ndarray, min_component: int) -> np.ndarray:
    """小さな点を除き、文字の左上を (0, 0) にそろえる。

    行の間隔が整数でなく、同じ文字でも 1〜2 画素ずれることがあるため。
    """
    keep = _keep_components(ink, min_component)
    ys, xs = np.nonzero(keep)
    out = np.zeros_like(ink)
    if len(ys):
        y0, x0 = ys.min(), xs.min()
        out[: ink.shape[0] - y0, : ink.shape[1] - x0] = keep[y0:, x0:]
    return out


def locate_glyph(img: np.ndarray, region: Region, dy: int, glyph: np.ndarray) -> tuple[int, int, int, int] | None:
    """region の中で、1 文字の見本 glyph（DIGIT_SHAPE）に最も近い文字の位置 (x, y, 幅, 高さ) を画像の座標で返す。

    ラベル入力の確認画像で、どの文字を切り取ったかを枠で示すために使う（読み取りには使わない）。
    """
    ink = region.threshold(img, dy)
    oy, ox = align_offset(ink, region.min_component)
    bits = align(ink, region.min_component)
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bits.astype(np.uint8), connectivity=8)
    best, best_dist = None, 1.0
    for c in range(1, n):
        x, y, w, h = (int(v) for v in stats[c, :4])
        part = (labels[y:y + h, x:x + w] == c)[: DIGIT_SHAPE[0], : DIGIT_SHAPE[1]]
        cand = np.zeros(DIGIT_SHAPE, dtype=bool)
        cand[: part.shape[0], : part.shape[1]] = part
        # "-" が隣の数字とつながっている形もあるので、右端をそろえた形とも比べる
        right = np.zeros(DIGIT_SHAPE, dtype=bool)
        tail = (labels[y:y + h, x:x + w] == c)[: DIGIT_SHAPE[0], -DIGIT_SHAPE[1]:]
        tail = tail[:, tail.any(axis=0).argmax():] if tail.any() else tail
        right[: tail.shape[0], : tail.shape[1]] = tail
        dist = min(iou_distance(glyph.reshape(1, -1), cand.reshape(-1))[0],
                   iou_distance(glyph.reshape(1, -1), right.reshape(-1))[0])
        if dist < best_dist:
            best, best_dist = (region.x0 + ox + x, region.y0 + dy + oy + y, w, h), dist
    return best


# 各項目の切り出し位置（1280x720 基準）。
NAME = Region(536, 366, 760, 389, "min", 100)
# レベルの四角（1 個 = 1 レベル）の中心。青 = 残ったレベル、赤 = 減った分、緑 = 増えた分、灰 = 空き
BAR_X0, BAR_PITCH, BAR_Y = 560, 16, 403
MAX_LEVEL = 8
ICON_X0, ICON_Y0, ICON_X1, ICON_Y1 = 521, 385, 539, 400   # スキル名の左のアイコン（1 行目）
VALUE_W, VALUE_H = 72, 22
SLOT = Region(660, 183, 762, 206, "gb", 50)
SKILL_DY = [0, 51, 101]    # 2・3 行目のずれ（間隔は約 50.5 画素）
MAX_SKILLS = len(SKILL_DY)
RESIST_NAMES = ["fire", "water", "thunder", "ice", "dragon"]
RESIST_Y = [207, 231, 256, 281, 303]


def value_region(y: int) -> Region:
    # 数値は色付き（緑・赤）と灰色（変化なしの "-"）があり、きらめき（薄いピンク）が重なることがある。
    # 最も明るい画素に対する割合で二値化すると、きらめきが消え、符号と数字の間のすき間も残る。
    return Region(690, y, 690 + VALUE_W, y + VALUE_H, "max", 0.6, min_component=3)


# 画面の種類。上から順に判定するので、見本が他の画面にも一致しうるもの（screen1 の見出しは
# screen2 にもある）は後ろに置く。dy は下の座標（screen1 基準）からの縦方向のずれ。
# 見本は --save-signature <名前> <画像> で作る。
LAYOUTS: dict[str, dict] = {
    # 強化後のステータスの下に「◀ L 1/2 R ▶」の切り替えがあり、以下が 25 画素下がる画面
    "screen2": {"signature": Region(570, 156, 612, 178, "min", 100), "dy": 25},
    # 「傀異強化結果」の見出し（右の飾りは出たり消えたりするので含めない）
    "screen1": {"signature": Region(400, 90, 565, 114, "min", 100), "dy": 0},
}

# 右上の所持金（黄色の数字、右寄せ、最大 8 桁）。画面の種類によらず位置は同じ。
# 値は画像ごとに毎回違うので、数値全体のテンプレートは作らず 1 文字ずつ照合する（フォントが
# 他の数値と違うので、文字テンプレートも別に持つ）。
MONEY = Region(1138, 18, 1226, 44, "max", 0.6, min_component=3)

FIELDS: dict[str, tuple[str, Region]] = {
    "defense": ("value", value_region(158)),
    "slot": ("slot", SLOT),
    **{name: ("value", value_region(y)) for name, y in zip(RESIST_NAMES, RESIST_Y)},
}

KIND_SHAPE = {"name": NAME.shape, "value": (VALUE_H, VALUE_W),
              "slot": SLOT.shape, "glyph": DIGIT_SHAPE, "money_glyph": DIGIT_SHAPE}

# slot_base は --base-slot で指定した初期スロット、slot_add はスロットのテンプレートのラベル（追加数）
OUTPUT_COLUMNS = ["defense", "slot_base", "slot_add", *RESIST_NAMES] + [
    c for i in range(MAX_SKILLS) for c in (f"skill{i + 1}", f"lv{i + 1}")
] + ["cost", "money_k"]
COLUMNS = ["defense", "slot", *RESIST_NAMES] + [
    c for i in range(MAX_SKILLS) for c in (f"skill{i + 1}", f"lv{i + 1}")
]


SKILL_COST = {name: cost for cost, names in SKILL_MASTER for name in names}
SLOT_COST = 6   # スロット 1 つ追加あたりのコスト


def calc_cost(values: dict[str, str]) -> str:
    """コスト = 6 × 追加スロット数 + Σ（レベルが上がったスキルのコスト × 上がったレベル）。

    レベルが下がったスキルはコストに含めない。値が読めていない（"?"）か、skill_master に
    無いスキルがあるときは "?"。

    属性耐性のコストは含めない。画面には属性ごとの合計しか出ないため、+2 が 1 回か +1 が 2 回か、
    プラスとマイナスが打ち消し合っていないかが分からず、画像から一意に決まらない
    （仕様の制約を使っても一意に決まるのは約 15%）。
    """
    if "?" in values["slot_add"]:
        return "?"
    cost = SLOT_COST * int(values["slot_add"])
    for i in range(1, MAX_SKILLS + 1):
        name, lv = values[f"skill{i}"], values[f"lv{i}"]
        if not name:
            continue
        if "?" in name or "?" in lv or name not in SKILL_COST:
            return "?"
        if int(lv) > 0:
            cost += SKILL_COST[name] * int(lv)
    return str(cost)


# ---------------------------------------------------------------- 切り出し

def load_image(path: str) -> tuple[np.ndarray, str] | None:
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    device = f"{img.shape[1]}x{img.shape[0]}"
    if (img.shape[1], img.shape[0]) != BASE_SIZE:
        img = cv2.resize(img, BASE_SIZE, interpolation=cv2.INTER_AREA)
    return img, device


_signatures: dict[str, np.ndarray] = {}


def signature_dir(template_dir: Path) -> Path:
    return template_dir / "screens"


def _init_worker(template_dir: Path) -> None:
    for layout in LAYOUTS:
        p = signature_dir(template_dir) / f"{layout}.png"
        sig = cv2.imread(str(p), cv2.IMREAD_GRAYSCALE) if p.exists() else None
        if sig is not None:
            _signatures[layout] = sig > 0


def iou_distance(bank: np.ndarray, bits: np.ndarray) -> np.ndarray:
    inter = (bank & bits).sum(axis=1)
    union = (bank | bits).sum(axis=1)
    # 両方とも空（変化なしで何も描かれない欄）は一致とみなす。1 にすると毎回新規登録される
    return np.where(union > 0, 1.0 - inter / np.maximum(union, 1), 0.0)


def block_distance(bank: np.ndarray, bits: np.ndarray, shape: tuple[int, int]) -> np.ndarray:
    """BLOCK_W 幅の区画ごとの 1 - IoU のうち、最も大きいもの（1 文字だけ違う、を見逃さないため）。"""
    h, w = shape
    nb = -(-w // BLOCK_W)
    pad = ((0, 0), (0, 0), (0, nb * BLOCK_W - w))
    a = np.pad(bank.reshape(-1, h, w), pad).reshape(-1, h, nb, BLOCK_W)
    b = np.pad(bits.reshape(1, h, w), pad).reshape(1, h, nb, BLOCK_W)
    inter = (a & b).sum(axis=(1, 3))
    union = (a | b).sum(axis=(1, 3))
    return np.where(union > 0, 1.0 - inter / np.maximum(union, 1), 0.0).max(axis=1)


def detect_screen(img: np.ndarray) -> str | None:
    for layout, sig in _signatures.items():
        bits = LAYOUTS[layout]["signature"].binarize(img)
        if iou_distance(sig.reshape(1, -1), bits.reshape(-1))[0] < SIGNATURE_THRESHOLD:
            return layout
    return None


def extract(path: str) -> dict | None:
    """1 枚分の各項目を二値化して返す。読めない画像は None、結果画面でなければ screen=None。"""
    loaded = load_image(path)
    if loaded is None:
        return None
    img, device = loaded
    screen = detect_screen(img)
    out = {"device": device, "screen": screen, "crops": {}, "levels": {}, "money": [], "features": {}}
    if screen is None:
        return out
    base = LAYOUTS[screen]["dy"]
    for field, (kind, region) in FIELDS.items():
        out["crops"][field] = (kind, np.packbits(region.binarize(img, base)))
    for i in range(MAX_SKILLS):
        dy = base + SKILL_DY[i]
        name = NAME.binarize(img, dy)
        if name.sum() < MIN_INK:
            break
        out["crops"][f"skill{i + 1}"] = ("name", np.packbits(name))
        out["levels"][f"lv{i + 1}"] = read_level_bar(img, dy)
        out["features"][i + 1] = skill_features(img, dy)
    out["money"] = [np.packbits(g) for g in split_glyphs(MONEY.binarize(img))]
    return out


def split_glyphs(bits: np.ndarray) -> list[np.ndarray]:
    """二値画像を連結成分ごとに左から切り出し、DIGIT_SHAPE の左上にそろえて返す。"""
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bits.astype(np.uint8), connectivity=8)
    glyphs = []
    for c in sorted(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_LEFT]):
        x, y, w, h = stats[c, :4]
        part = (labels[y:y + h, x:x + w] == c)[: DIGIT_SHAPE[0], : DIGIT_SHAPE[1]]
        glyph = np.zeros(DIGIT_SHAPE, dtype=bool)
        glyph[: part.shape[0], : part.shape[1]] = part
        glyphs.append(glyph)
    return glyphs


def square_color(pixel: np.ndarray) -> str:
    """レベルの四角 1 個の色。明るい色付きのもの以外（灰色の空き・背景・赤い演出光）は ""。

    赤い四角は R≒180、レア演出で赤く光った背景は R≒100 なので、その間で区切る。
    """
    b, g, r = (int(v) for v in pixel)
    if max(b, g, r) < 130:
        return ""
    if g > r + 60 and g > b + 60:
        return "G"
    if r > g + 60 and r > b + 60:
        return "R"
    if b > r + 60:
        return "B"
    return "?"


def read_level_bar(img: np.ndarray, dy: int) -> str:
    """スキル名の下の四角を数え、レベルの増減を "+1" "-2" などで返す。

    サンプル全体で、文字 "Lv +n" がオレンジになるのは空き（灰色）が無い＝最大レベルに
    達したとき、緑になるのは空きが残っているときだった。色は増減の判定には使わない。
    """
    y = BAR_Y + dy
    colors = [square_color(np.median(img[y - 1:y + 2, x - 1:x + 2].reshape(-1, 3), axis=0))
              for x in range(BAR_X0, BAR_X0 + BAR_PITCH * MAX_LEVEL, BAR_PITCH)]
    delta = colors.count("G") - colors.count("R")
    if "?" in colors or delta == 0:
        return "?"
    return f"{delta:+d}"


def skill_features(img: np.ndarray, dy: int) -> dict[str, str]:
    """整合性チェック用に、スキル 1 行分の見た目を記録する。

    bar   : 四角の並び（G 緑 / R 赤 / B 青 / g 空きの灰色 / ? 不明）。長さ = そのスキルの最大レベル
    color : "Lv ±n" の文字色（green / orange / red）
    icon  : スキル名の左のアイコンの色（明るい画素の BGR 中央値, "b:g:r"）
    """
    y = BAR_Y + dy
    bar = ""
    for x in range(BAR_X0, BAR_X0 + BAR_PITCH * MAX_LEVEL, BAR_PITCH):
        px = np.median(img[y - 1:y + 2, x - 1:x + 2].reshape(-1, 3), axis=0)
        c = square_color(px)
        if not c:
            b, g, r = (int(v) for v in px)
            if max(b, g, r) < 38 or max(b, g, r) - min(b, g, r) >= 12:   # 空きの灰色は差が 5 程度
                break                   # 四角の並びの終わり（背景。赤く光った背景も含む）
            c = "g"
        bar += c
    text = img[392 + dy:414 + dy, 700:762].astype(int)
    ink = text.max(axis=2) > 150
    color = ""
    if ink.sum() >= 10:
        b, g, r = (text[..., k][ink].mean() for k in range(3))
        color = "green" if g > r + 60 else "orange" if (r > 150 and g > 90) else "red" if r > g + 60 else "?"
    icon = img[ICON_Y0 + dy:ICON_Y1 + dy, ICON_X0:ICON_X1].reshape(-1, 3).astype(int)
    bright = icon[icon.max(axis=1) > 110]
    icon_s = ":".join(str(int(v)) for v in np.median(bright, axis=0)) if len(bright) >= 8 else ""
    return {"bar": bar, "color": color, "icon": icon_s}


def extract_batch(paths: list[str]) -> list[dict | None]:
    return [extract(p) for p in paths]


# ---------------------------------------------------------------- テンプレート

class TemplateBank:
    """本体 × 項目種別ごとの、二値化画像とラベルの対応表。

    ラベルは templates/<本体>_<種別>.json に保存される。スロットと数字のラベルは
    templates/review/ の拡大画像を見ながら手で書き換える。
    """

    def __init__(self, template_dir: Path, device: str, kind: str, variant: str = "") -> None:
        self.template_dir = template_dir
        self.device, self.kind = device, kind
        self.shape = KIND_SHAPE[kind]
        self.bits = np.zeros((0, self.shape[0] * self.shape[1]), dtype=bool)
        self.labels: list[str | None] = []
        self.sources: list[tuple[str, str] | None] = []   # 新規テンプレートの元画像と項目（OCR 用）
        self.variant = variant   # 同じ種別でテンプレートを分けるときの接尾辞（スロットの "_base3" など）
        stem = template_dir / f"{device}_{kind}{variant}"
        self.npz_path, self.json_path = stem.with_suffix(".npz"), stem.with_suffix(".json")
        if self.npz_path.exists():
            self.bits = np.load(self.npz_path)["bits"]
            self.labels = json.loads(self.json_path.read_text(encoding="utf-8"))
            self.sources = [None] * len(self.labels)
        self.new_from = len(self.labels)
        self.cache: dict[bytes, int] = {}

    @property
    def name(self) -> str:
        return f"{self.device}_{self.kind}{self.variant}"

    def is_unlabeled(self, i: int) -> bool:
        """ラベルが確定していないか。未設定のほか、スロットの "?slot#n"（未設定の印）と、
        スキル名の "…?"（EasyOCR の読みで候補が僅差だったもの）も確定していないとみなす。"""
        label = self.labels[i]
        if label is None:
            return True
        return self.kind in ("name", "slot") and "?" in label

    def match(self, bits: np.ndarray, source: tuple[str, str] | None = None) -> int:
        """一致するテンプレート番号を返す。無ければ新規登録する。"""
        bits = bits.reshape(-1)
        if len(self.labels):
            whole, block = MATCH_THRESHOLD.get(self.kind, MATCH_THRESHOLD["default"])
            dist = iou_distance(self.bits, bits)
            dist = np.where(block_distance(self.bits, bits, self.shape) < block, dist, 1.0)
            best = int(dist.argmin())
            if dist[best] < whole:
                # 保存済みのテンプレートは元画像が分からないので、最初に当たった画像を覚えておく
                # （ラベルが確定していない見本の確認画像と、EasyOCR でのラベル付けに使う）
                if self.sources[best] is None:
                    self.sources[best] = source
                return best
        self.bits = np.vstack([self.bits, bits])
        self.labels.append(None)
        self.sources.append(source)
        return len(self.labels) - 1

    def unpack(self, packed: np.ndarray) -> np.ndarray:
        return np.unpackbits(packed)[: self.bits.shape[1]].astype(bool)

    def save(self) -> None:
        self.template_dir.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.npz_path, bits=self.bits)
        self.json_path.write_text(json.dumps(self.labels, ensure_ascii=False, indent=1), encoding="utf-8")
        review = self.template_dir / "review" / self.name
        review.mkdir(parents=True, exist_ok=True)
        for i in range(self.new_from, len(self.labels)):
            img = self.bits[i].reshape(self.shape).astype(np.uint8) * 255
            cv2.imwrite(str(review / f"{i:04d}.png"), cv2.resize(img, None, fx=4, fy=4, interpolation=cv2.INTER_NEAREST))


# ---------------------------------------------------------------- ラベル付け

def snap_to_master(text: str) -> tuple[str, float]:
    """OCR 結果を skill_master の最も近いスキル名に補正する。

    候補が僅差で並ぶとき（例: OCR "優速度" は 回復速度 と 装填速度 が同点）は
    名前の末尾に "?" を付けて要確認にする。templates/*_name.json を直せば次回から反映される。
    """
    # 画面は "ＫＯ術" "ＵＰ" のように全角英数字、skill_master は半角なのでそろえる
    text = unicodedata.normalize("NFKC", text).replace(" ", "")
    scored = sorted(((difflib.SequenceMatcher(None, text, unicodedata.normalize("NFKC", s)).ratio(), s)
                     for s in ALL_MASTER_SKILL_NAMES), reverse=True)
    (score, best), (second, _) = scored[0], scored[1]
    return (best + "?" if score - second < AMBIGUOUS_MARGIN else best), score


def read_number(bits: np.ndarray, glyphs: TemplateBank, source: tuple[str, str] | None = None) -> str:
    """二値化済みの '+24' '-3' '-'（変化なし）などを 1 文字ずつ文字テンプレートと照合して読む。

    EasyOCR は "-" や 1 桁の数字を読み落とすので使わない。"-" は数画素しかなく
    テンプレート照合では揺れるので、横長の形かどうかで判定する。それ以外の文字は
    テンプレートにし、ラベル（"+" "0"〜"9"）は手で付ける。
    ラベルが空文字 "" の文字はノイズ（演出の粒など）として無視する。読めない文字は '?'。
    source（この数値の元画像と項目）は新しい文字テンプレートに記録し、ラベル入力の確認画像に使う。

    灰色の "-"（変化なし）は暗いため、近くに明るい演出の粒があると二値化で消える。
    色付きの数値は粒より明るく消えないので、何も残らなければ "-" とみなす。
    """
    n, labels, stats, _ = cv2.connectedComponentsWithStats(bits.astype(np.uint8), connectivity=8)
    text = ""
    # 数字・"+" の上下の範囲。"-" はその中央付近にあるので、上端・下端の横長の粒（演出）は除く
    tall = [c for c in range(1, n) if stats[c, cv2.CC_STAT_HEIGHT] > 5]
    top = bottom = 0   # tall が無いときは使わない
    if tall:
        top = min(stats[c, cv2.CC_STAT_TOP] for c in tall)
        bottom = max(stats[c, cv2.CC_STAT_TOP] + stats[c, cv2.CC_STAT_HEIGHT] for c in tall)
    for c in sorted(range(1, n), key=lambda i: stats[i, cv2.CC_STAT_LEFT]):
        x, y, w, h = stats[c, :4]
        part = labels[y:y + h, x:x + w] == c
        if h <= 4 and w >= max(3, 2 * h):
            margin = (bottom - top) * 0.2 if tall else 0
            if not tall or top + margin <= y + h / 2 <= bottom - margin:
                text += "-"
            continue
        if h <= 5:   # 横長でない小さな点は演出の粒（数字・"+" はもっと背が高い）
            continue
        # "-" が隣の数字とつながった場合は、左端の横棒部分（高さ 4 以下の列）を切り離す。
        # "7" の上辺と区別するため横棒が上下の中央付近にあるときだけ、
        # "+" と区別するため右端も横棒（高さ 4 以下）で終わる形は除く。
        heights = part.sum(axis=0)
        bar = int(np.argmax(heights > 4)) if (heights > 4).any() else w
        rows = np.nonzero(part[:, :bar].any(axis=1))[0] if bar else np.array([], dtype=np.intp)
        is_plus = heights[-1] <= 4 and (heights > 4).sum() <= 3
        if 3 <= bar < w and not is_plus and rows.max() - rows.min() < 4 and h * 0.3 <= rows.mean() <= h * 0.7:
            text += "-"
            part = part[:, bar:]
            part = part[part.any(axis=1)]
            if not part.any():
                continue
        glyph = np.zeros(DIGIT_SHAPE, dtype=bool)
        part = part[: DIGIT_SHAPE[0], : DIGIT_SHAPE[1]]
        glyph[: part.shape[0], : part.shape[1]] = part
        label = glyphs.labels[glyphs.match(glyph, source)]
        text += "?" if label is None else label
    # 灰色の "-" のそばに演出の粒（横長の小さな点）があると "--" になる。本物の値に "-" が
    # 2 つ続くことは無いので 1 つにまとめる
    while "--" in text:
        text = text.replace("--", "-")
    return text or "-"


def read_money(glyphs: TemplateBank, ids: list[int]) -> str:
    """所持金を 1000 単位で返す（下 3 桁は捨てる）。ラベル "" の文字はノイズとして無視、未設定は "?"。"""
    labels = [glyphs.labels[i] for i in ids]
    if any(lab is None for lab in labels):
        return "?"
    digits = "".join(lab or "" for lab in labels)
    return digits[:-3] if len(digits) > 3 and digits.isdigit() else "?"


def easyocr_available() -> bool:
    try:
        import easyocr  # noqa: F401  # pyright: ignore[reportMissingImports]
    except ImportError:
        return False
    return True


def label_names(bank: TemplateBank, screen_of: dict[str, str]) -> list[tuple[int, str, str, float]]:
    """ラベル未設定のスキル名テンプレートを EasyOCR で読む。(番号, OCR文字列, ラベル, 類似度) を返す。

    EasyOCR が入っていない環境（配布版）では何もしない。ラベルは未設定のまま残り、
    そのテンプレートに当たったスキル名は "?"（要確認）になる。
    元画像が分からないもの（前回の実行で作られ、今回は当たらなかったもの）も飛ばす。
    """
    todo = [i for i, lab in enumerate(bank.labels) if lab is None and bank.sources[i] is not None]
    if not todo or not easyocr_available():
        return []
    import easyocr  # 読み込みが重いので必要なときだけ  # pyright: ignore[reportMissingImports]

    reader = easyocr.Reader(["ja"], gpu=False, verbose=False)
    report = []
    for i in todo:
        source = bank.sources[i]
        loaded = load_image(source[0]) if source is not None else None
        if source is None or loaded is None:
            continue
        path, field = source
        img = loaded[0]
        dy = LAYOUTS[screen_of[path]]["dy"] + SKILL_DY[int(field[-1]) - 1]
        crop = img[NAME.y0 + dy - 4:NAME.y1 + dy + 4, NAME.x0 - 4:NAME.x1]
        crop = cv2.resize(crop, None, fx=3, fy=3, interpolation=cv2.INTER_CUBIC)
        text = "".join(reader.readtext(crop, detail=0))
        name, score = snap_to_master(text)
        bank.labels[i] = name
        report.append((i, text, name, score))
    return report


# ---------------------------------------------------------------- 確認用

def write_slot_sheet(out: str, paths: list[str], results: list, screen_of: dict[str, str]) -> None:
    """スロットのテンプレートごとに、ラベル・枚数・実画像の例（最大 3 枚、カラー・2 倍）を 1 行に並べる。

    二値化したテンプレート画像では緑に塗られたアイコンが輪郭だけになり見分けにくいので、元画像で確認する。
    """
    from PIL import Image, ImageDraw, ImageFont  # pyright: ignore[reportMissingImports]

    members: dict[int, list[str]] = {}
    counts: dict[int, int] = {}
    bank = None
    for path, ids in zip(paths, results):
        if ids is None or "slot" not in ids:
            continue
        bank, tid = ids["slot"]
        counts[tid] = counts.get(tid, 0) + 1
        if len(members.setdefault(tid, [])) < 3:
            members[tid].append(path)
    if bank is None:
        return
    font = ImageFont.truetype("C:/Windows/Fonts/meiryo.ttc", 18)
    label_w, rows = 280, []
    for tid in sorted(members, key=lambda t: (str(bank.labels[t]), t)):
        crops = []
        for path in members[tid]:
            loaded = load_image(path)
            if loaded is None:
                continue
            img = loaded[0]
            dy = LAYOUTS[screen_of[path]]["dy"]
            crop = img[SLOT.y0 + dy - 8:SLOT.y1 + dy + 6, 505:SLOT.x1 + 10]   # 「スロット」の文字から右端まで
            crops.append(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        if not crops:
            continue
        h, w = crops[0].shape[:2]
        row = Image.new("RGB", (label_w + 3 * (w + 8), h + 4), (30, 30, 60))
        for i, crop in enumerate(crops):
            row.paste(Image.fromarray(cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)), (label_w + i * (w + 8), 2))
        ImageDraw.Draw(row).text((8, h // 2 - 12), f"#{tid}  {bank.labels[tid]}  ({counts[tid]}枚)", font=font, fill=(255, 255, 0))
        rows.append(row)
    sheet = Image.new("RGB", (rows[0].width, sum(r.height for r in rows)))
    y = 0
    for r in rows:
        sheet.paste(r, (0, y))
        y += r.height
    sheet.save(out)
    print(f"スロットの確認用画像 -> {out}")


# ---------------------------------------------------------------- 出力

REPORT_SKILLS = 6   # 出力形式の第 1〜6 スキル（画像から読めるのは 3 つまで）


def write_detail_csv(out: str, records: list) -> None:
    with open(out, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        feat_cols = [f"{k}{i}" for i in range(1, MAX_SKILLS + 1) for k in ("bar", "color", "icon")]
        writer.writerow(["file", "status", "screen", "device"] + OUTPUT_COLUMNS + feat_cols)
        for name, ex, values in records:
            if ex is None:
                writer.writerow([name, "read_error"])
            elif values is None:
                writer.writerow([name, "not_result", "", ex["device"]])
            else:
                row = [values[c] for c in OUTPUT_COLUMNS]
                status = "check" if any("?" in v for v in row) else "ok"
                feats = [ex["features"].get(i, {}).get(k, "") for i in range(1, MAX_SKILLS + 1)
                         for k in ("bar", "color", "icon")]
                writer.writerow([name, status, ex["screen"], ex["device"]] + row + feats)


def report_row(values: dict, screen: str) -> list[str]:
    """回数・ゼニーを除いた 1 行分（スロ, コスト, マイナス, 耐性, 第1名, 第1値, …, 対象）。"""
    slot = values["slot_add"]
    levels = [values[f"lv{i}"] for i in range(1, MAX_SKILLS + 1) if values[f"skill{i}"]]
    if any("?" in lv for lv in levels):
        minus = "?"
    else:
        minus = "有" if any(int(lv) < 0 for lv in levels) else "無"
    resists = [values[r] for r in RESIST_NAMES]
    resist = "?" if any("?" in v for v in resists) else str(sum(0 if v == "-" else int(v) for v in resists))
    skills = []
    for i in range(1, MAX_SKILLS + 1):
        name, lv = values[f"skill{i}"], values[f"lv{i}"]
        if name:
            skills += [name, lv if "?" in lv else str(int(lv))]
    if screen == "screen2":
        # スキルが 4 つ以上あり 2 ページ目がある画面。4 つ目以降は写っていないので印を付ける
        skills += [UNKNOWN_SKILL_NAME, ""]
    skills += [""] * (2 * REPORT_SKILLS - len(skills))
    return ["?" if "?" in slot else str(int(slot)), values["cost"], minus, resist, *skills, "0"]


@dataclass
class Report:
    text: str          # 「初期ゼニー / 回数,ゼニー,スロ,…」の形式（qurious-crafting-log の取込形式）
    errors: list[str]  # ゼニーの減り方・ゲームの仕様との矛盾（自己チェック）
    line_count: int
    duplicate_count: int   # 同じ回の重複として除いた枚数


def build_report(records: list, step_k: int, template_dir: Path,
                 minus_skills: dict[str, int] | None = None) -> Report:
    """結果を「初期ゼニー / 回数,ゼニー,スロ,…」の形式にする。

    回数は所持金から求める: (初期ゼニー - ゼニー) / 1 回の金額。初期ゼニーは 1 枚目のゼニー + 1 回分。
    同じ回を複数枚撮った画像は 1 枚だけ残す。読めていない値（"?"）の無い画像を優先し、
    どちらも同じ条件なら先の 1 枚。結果画面以外の画像はここに来る前に除かれている。
    ゼニーは千単位（下 3 桁は捨てる）。
    """
    rows = [(name, ex["screen"], v) for name, ex, v in records if v is not None]
    first = next((v["money_k"] for _, _, v in rows if "?" not in v["money_k"]), None)
    init = int(first) + step_k if first is not None else None
    seen: dict[int, tuple[str, list[str]]] = {}
    lines: list[tuple[str, str, list[str]]] = []   # (回数, ゼニー, 残り)
    line_of: dict[int, int] = {}                   # 回数 -> lines の位置
    warnings, dup = [], 0
    for name, screen, v in rows:
        body = report_row(v, screen)
        if init is None or "?" in v["money_k"]:
            count = "?"
            warnings.append(f"{name}: ゼニーが読めないため回数が不明")
        else:
            spent = init - int(v["money_k"])
            if spent <= 0 or spent % step_k:
                count = "?"
                warnings.append(f"{name}: ゼニー {v['money_k']} が 1 回 {step_k * 1000} の減り方と合わない")
            else:
                count = spent // step_k
                if count in seen:
                    dup += 1
                    kept_name, kept_body = seen[count]
                    if "?" in "".join(kept_body) and "?" not in "".join(body):
                        seen[count] = (name, body)   # 前の画像は読めていない値があるので、こちらに差し替える
                        lines[line_of[count]] = (str(count), v["money_k"], body)
                    elif kept_body != body and "?" not in "".join(body):
                        warnings.append(f"{name}: {count} 回目が {kept_name} と重複しているが内容が違う（{kept_name} を残した）")
                    continue
                seen[count] = (name, body)
                line_of[count] = len(lines)
        lines.append((str(count), v["money_k"], body))
    header = ["回数", "ゼニー", "スロ", "コスト", "マイナス", "耐性"]
    header += [f"第{i}{k}" for i in range(1, REPORT_SKILLS + 1) for k in ("名", "値")] + ["対象"]
    text = (f"初期ゼニー,{init if init is not None else '?'}\n" + ",".join(header) + "\n"
            + "\n".join(",".join([c, z, *b]) for c, z, b in lines) + "\n")
    errors = warnings + check_sequence(rows, step_k) + check_consistency(records, template_dir, minus_skills)
    return Report(text, errors, len(lines), dup)


def write_report(out: str, report: Report) -> None:
    """build_report の結果を out と「out の名前_errors.txt」に書く（CLI 用）。"""
    with open(out, "w", encoding="utf-8", newline="\n") as f:
        f.write(report.text)
    errors = report.errors
    err_path = Path(out).with_name(Path(out).stem + "_errors.txt")
    with open(err_path, "w", encoding="utf-8", newline="\n") as f:
        f.write("\n".join(errors) + ("\n" if errors else ""))
    print(f"出力 {report.line_count} 回分 -> {out}（同じ回の重複を除いた枚数 {report.duplicate_count}）",
          file=sys.stderr)
    if errors:
        print(f"エラー {len(errors)} 件 -> {err_path}", file=sys.stderr)
        for e in errors[:10]:
            print("  " + e, file=sys.stderr)
        if len(errors) > 10:
            print(f"  ほか {len(errors) - 10} 件", file=sys.stderr)
    else:
        print("エラーなし（ゼニーの減り方・ゲームの仕様との矛盾なし）", file=sys.stderr)


SKILL_PROPS_FILE = "skill_props.json"
ICON_TOLERANCE = 45          # アイコンの色の差（BGR の距離）。同じスキルの揺れは最大 25 程度、雷と龍は約 135
VALUE_LIMITS = {"defense": 50, "resist": 12, "level": 4}   # これを超える増減はあり得ないとみなす


def check_consistency(records: list, template_dir: Path,
                      minus_skills: dict[str, int] | None = None) -> list[str]:
    """ゲームの仕様から、読み取り結果の矛盾を探す。

      - 四角の総数（そのスキルの最大レベル）がスキルごとに決まった数か
      - スキル名の左のアイコンの色が、そのスキルの色か（「雷」と「龍」の取り違えなどに気付ける）
      - "Lv ±n" の文字色: 減った = 赤、増えて空きが残る = 緑、増えて最大に達した = オレンジ
      - 防御力・耐性・レベルの増減が、あり得る範囲か
      - minus_skills（防具が元から持つスキル -> 元のレベル）を渡したとき、下がったスキルがその中にあり、
        元のレベルより多く下がっていないか（レベルが下がるのは防具が元から持つスキルだけ）
    スキルの最大レベルとアイコンの色は templates/skill_props.json（確認済みのデータから作った表）と比べる。
    表に無いスキルは、この回の値で登録し、その旨を知らせる。
    """
    props_path = template_dir / SKILL_PROPS_FILE
    props = json.loads(props_path.read_text(encoding="utf-8")) if props_path.exists() else {}
    errors, added = [], {}
    for name, ex, v in records:
        if v is None:
            continue
        for key in ["defense", *RESIST_NAMES]:
            limit = VALUE_LIMITS["defense" if key == "defense" else "resist"]
            if v[key] not in ("-", "") and "?" not in v[key] and abs(int(v[key])) > limit:
                errors.append(f"{name}: {key} の増減 {v[key]} があり得る範囲（±{limit}）を超えている")
        for i in range(1, MAX_SKILLS + 1):
            skill, lv, feat = v[f"skill{i}"], v[f"lv{i}"], ex["features"].get(i)
            if not skill or feat is None or "?" in skill + lv:
                continue
            where = f"{name}: {i} つ目のスキル {skill} {lv}"
            if abs(int(lv)) > VALUE_LIMITS["level"]:
                errors.append(f"{where} のレベルの増減があり得る範囲を超えている")
            expected = "red" if int(lv) < 0 else "green" if "g" in feat["bar"] else "orange"
            if feat["color"] != expected:
                errors.append(f"{where} の文字色が {feat['color']}（四角の並び {feat['bar']} からは {expected} のはず）")
            if minus_skills is not None and int(lv) < 0:
                if skill not in minus_skills:
                    errors.append(f"{where}: 防具が元から持たないスキルが下がっている（下がるのは {'・'.join(minus_skills)} だけ）")
                elif -int(lv) > minus_skills[skill]:
                    errors.append(f"{where}: 元のレベル {minus_skills[skill]} より多く下がっている")
            if skill not in props:
                added.setdefault(skill, (len(feat["bar"]), feat["icon"], name))
                continue
            if len(feat["bar"]) != props[skill]["max"]:
                errors.append(f"{where} の四角が {len(feat['bar'])} 個（{skill} は {props[skill]['max']} 個のはず。"
                              "スキル名かレベルの読み違いの疑い）")
            if feat["icon"]:
                icon = np.array([int(x) for x in feat["icon"].split(":")])
                if np.linalg.norm(icon - np.array(props[skill]["icon"])) > ICON_TOLERANCE:
                    errors.append(f"{where} のアイコンの色 {feat['icon']} が {skill} の色と違う（スキル名の読み違いの疑い）")
    for skill, (mx, icon, name) in added.items():
        props[skill] = {"max": mx, "icon": [int(x) for x in icon.split(":")] if icon else [], "unverified": name}
        print(f"新しいスキル {skill} の性質（最大レベル {mx}、アイコンの色 {icon}）を {name} から登録しました。"
              "画像で確認してください", file=sys.stderr)
    if added:
        props_path.write_text(json.dumps(props, ensure_ascii=False, indent=1), encoding="utf-8")
    return errors


def check_sequence(rows: list, step_k: int) -> list[str]:
    """撮影順に並べた結果画面について、ゼニーが「正常に 1 回分減っている」かを調べ、そうでない所を返す。

    正常とみなすのは、直前の結果画面（ゼニーが読めたもの）と比べて
      - ちょうど 1 回分（step_k）減っている
      - 減っていない（同じ回を撮り直した）うえで、読み取った内容も同じ
    のどちらか。ファイル名はスイッチの撮影日時なので、名前順を撮影順とする。
    """
    errors = []
    prev = None   # (ファイル名, ゼニー, 内容)
    for name, screen, v in rows:
        if "?" in v["money_k"]:
            continue   # ゼニーが読めない画像は write_report 側でエラーにしている
        money, body = int(v["money_k"]), report_row(v, screen)
        if prev is not None:
            p_name, p_money, p_body = prev
            diff = p_money - money
            where = f"{p_name} ({p_money}) -> {name} ({money})"
            if diff == step_k:
                pass
            elif diff == 0:
                if p_body != body:
                    errors.append(f"ゼニーが同じなのに内容が違う: {where}")
            elif diff > 0 and diff % step_k == 0:
                errors.append(f"{diff // step_k - 1} 回分撮れていない: {where}")
            elif diff < 0:
                errors.append(f"ゼニーが増えている（別の記録が混ざっている、または読み間違い）: {where}")
            else:
                errors.append(f"減り方が 1 回 {step_k * 1000} の倍数でない（読み間違いか --zenny-step の指定違い）: {where}")
        prev = (name, money, body)
    return errors


# ---------------------------------------------------------------- 実行

ProgressCallback = Callable[[int, int], None]
EXTRACT_CHUNK = 64


def user_template_dir(data_dir: Path) -> Path:
    """アプリが使う見本の置き場所（data_dir/ocr_templates）。無ければ同梱の見本を複製して作る。

    インストール先（Program Files）には書き込めず、新しい見本や skill_props.json の追記が
    保存できないため、DB と同じユーザーのデータフォルダに複製して使う。
    """
    dst = data_dir / "ocr_templates"
    if not dst.exists():
        shutil.copytree(BUNDLED_TEMPLATE_DIR, dst, ignore=shutil.ignore_patterns("review"))
    return dst


def parse_minus_skills(text: str) -> dict[str, int] | None:
    """「攻撃:2,火事場力:3」を {"攻撃": 2, "火事場力": 3} にする。空なら None。形式が違えば ValueError。"""
    text = text.strip()
    if not text:
        return None
    return {s.strip(): int(lv) for s, lv in (x.rsplit(":", 1) for x in text.replace("，", ",").split(","))}


def list_images(inputs: list[str | Path]) -> list[str]:
    """フォルダは中の *.jpg を名前順（= Switch の撮影日時順）に、ファイルはそのまま並べる。"""
    paths: list[str] = []
    for item in inputs:
        p = Path(item)
        paths += sorted(str(f) for f in p.glob("*.jpg")) if p.is_dir() else [str(p)]
    return paths


@dataclass
class OcrRun:
    report: Report
    records: list                  # [(ファイル名, 切り出し結果, 読み取った値)]
    paths: list[str]
    results: list                  # 画像ごとの (テンプレート, 番号)。write_slot_sheet 用
    screen_of: dict[str, str]
    banks: list[TemplateBank]
    name_report: dict[str, list[tuple[int, str, str, float]]]
    template_dir: Path
    timings: dict[str, float] = field(default_factory=dict)

    @property
    def screen_counts(self) -> dict[str, int]:
        return {k: sum(ex is not None and ex["screen"] == k for _, ex, _ in self.records) for k in LAYOUTS}

    @property
    def not_result_count(self) -> int:
        return sum(ex is not None and ex["screen"] is None for _, ex, _ in self.records)

    @property
    def read_error_count(self) -> int:
        return sum(ex is None for _, ex, _ in self.records)

    @property
    def new_template_count(self) -> int:
        return sum(len(b.labels) - b.new_from for b in self.banks)

    @property
    def unlabeled(self) -> dict[str, int]:
        """ラベルが確定していない見本の数（見本の種類ごと）。読み取り結果の "?" の原因になる。"""
        out = {}
        for b in self.banks:
            if b.kind == "value":
                continue   # 数値は glyph から組み立てる
            n = sum(b.is_unlabeled(i) for i in range(len(b.labels)))
            if n:
                out[b.name] = n
        return out


# ラベル入力の選択肢（名前以外）。"" はノイズ（演出の粒など）として無視する文字
LABEL_CHOICES: dict[str, list[str]] = {
    "glyph": [*"0123456789", "+", ""],
    "money_glyph": [*"0123456789", ""],
    "slot": [f"+{n}" for n in range(7)],
}
KIND_TITLES = {"name": "スキル名", "glyph": "防御力・耐性の文字", "money_glyph": "所持ゼニーの文字",
               "slot": "追加スロット数"}


def label_choices(kind: str) -> list[str]:
    """見本の種類ごとの、付けられるラベルの一覧。"""
    if kind == "name":
        return [name for _, names in SKILL_MASTER for name in names]
    return LABEL_CHOICES[kind]


@dataclass
class PendingLabel:
    """ラベルが確定していない見本 1 つ。アプリではユーザーに正しいラベルを選んでもらう。"""
    bank: TemplateBank
    index: int
    image_png: bytes   # 確認用の画像（元画像が分かればカラーの切り出し、無ければ二値化した見本の拡大）
    glyph_png: bytes   # 文字の見本だけ: 二値化した 1 文字の拡大（image_png はその文字を含む欄）
    guess: str         # 候補（EasyOCR の読みなど。無ければ ""）
    count: int         # この回の画像で当たった枚数（文字の見本は数えていないので 0）

    @property
    def kind(self) -> str:
        return self.bank.kind

    @property
    def key(self) -> tuple[str, int]:
        return self.bank.name, self.index


def _png(img: np.ndarray, scale: int) -> bytes:
    img = cv2.resize(img, None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    ok, buf = cv2.imencode(".png", img)
    return buf.tobytes() if ok else b""


BOX_COLOR = (0, 0, 255)   # 確認画像で切り取った文字を囲む枠の色（BGR の赤）


def _png_with_box(img: np.ndarray, area: tuple[int, int, int, int],
                  box: tuple[int, int, int, int] | None, scale: int) -> bytes:
    """img の area (y0, y1, x0, x1) を scale 倍にし、box (x, y, 幅, 高さ) を赤枠で囲んだ PNG。"""
    y0, y1, x0, x1 = area
    out = cv2.resize(img[y0:y1, x0:x1], None, fx=scale, fy=scale, interpolation=cv2.INTER_NEAREST)
    if box is not None:
        x, y, w, h = box
        cv2.rectangle(out, ((x - x0) * scale - 3, (y - y0) * scale - 3),
                      ((x - x0 + w) * scale + 2, (y - y0 + h) * scale + 2), BOX_COLOR, 2)
    ok, buf = cv2.imencode(".png", out)
    return buf.tobytes() if ok else b""


@dataclass
class OcrSession:
    """画像の切り出しと見本との照合まで済ませた途中の状態。

    ラベルが確定していない見本があれば pending_labels() で取り出し、apply_labels() で
    ラベルを付けてから finish_reading() で結果を作る。
    """
    paths: list[str]
    extracted: list[dict | None]
    base_slot: int
    zenny_step: int
    minus_skills: dict[str, int] | None
    template_dir: Path
    banks: dict[tuple[str, str], TemplateBank] = field(default_factory=dict)
    results: list[dict | None] = field(default_factory=list)
    screen_of: dict[str, str] = field(default_factory=dict)
    name_report: dict[str, list[tuple[int, str, str, float]]] = field(default_factory=dict)
    timings: dict[str, float] = field(default_factory=dict)

    def bank(self, device: str, kind: str) -> TemplateBank:
        if (device, kind) not in self.banks:
            self.banks[device, kind] = TemplateBank(self.template_dir, device, kind,
                                                    f"_base{self.base_slot}" if kind == "slot" else "")
        return self.banks[device, kind]

    def build_values(self) -> None:
        """数値は数字テンプレートのラベルから毎回組み立てる（数字のラベルを直せば反映される）。

        組み立ての途中で、まだ無い形の文字は数字テンプレートに新規登録される。
        """
        for b in list(self.banks.values()):
            if b.kind == "value":
                glyphs = self.bank(b.device, "glyph")
                b.labels = [read_number(bits.reshape(b.shape), glyphs, b.sources[i]) for i, bits in enumerate(b.bits)]

    def hit_counts(self) -> dict[tuple[str, int], int]:
        counts: dict[tuple[str, int], int] = {}
        for ids in self.results:
            for fld, entry in (ids or {}).items():
                if fld == "money":
                    continue
                b, i = entry
                counts[b.name, i] = counts.get((b.name, i), 0) + 1
        return counts

    def pending_labels(self) -> list[PendingLabel]:
        """ラベルが確定していない見本（数値は文字の見本から組み立てるので除く）。"""
        counts = self.hit_counts()
        pending = []
        for b in self.banks.values():
            if b.kind == "value":
                continue
            for i in range(len(b.labels)):
                if b.is_unlabeled(i):
                    guess = (b.labels[i] or "").rstrip("?")
                    if b.kind == "slot" and guess.startswith("?"):
                        guess = ""
                    glyph = (_png(b.bits[i].reshape(b.shape).astype(np.uint8) * 255, 4)
                             if b.kind in ("glyph", "money_glyph") else b"")
                    pending.append(PendingLabel(b, i, self._label_image(b, i), glyph, guess,
                                                counts.get((b.name, i), 0)))
        return pending

    def _label_image(self, b: TemplateBank, i: int) -> bytes:
        source = b.sources[i]
        loaded = load_image(source[0]) if source is not None and source[0] in self.screen_of else None
        if source is not None and loaded is not None:
            path, fld = source
            img = loaded[0]
            dy = LAYOUTS[self.screen_of[path]]["dy"]
            if b.kind == "name":
                dy += SKILL_DY[int(fld[-1]) - 1]
                return _png(img[NAME.y0 + dy - 4:NAME.y1 + dy + 4, NAME.x0 - 24:NAME.x1], 2)
            if b.kind == "slot":
                return _png(img[SLOT.y0 + dy - 8:SLOT.y1 + dy + 6, 505:SLOT.x1 + 10], 2)
            glyph = b.bits[i].reshape(b.shape)
            if b.kind == "money_glyph":
                box = locate_glyph(img, MONEY, 0, glyph)
                return _png_with_box(img, (MONEY.y0 - 6, MONEY.y1 + 6, MONEY.x0 - 40, MONEY.x1 + 6), box, 2)
            if b.kind == "glyph" and fld in FIELDS:
                region = FIELDS[fld][1]   # 項目名（防御力・火耐性など）から数値の右端まで
                box = locate_glyph(img, region, dy, glyph)
                return _png_with_box(img, (region.y0 + dy - 2, region.y1 + dy + 2, 505, region.x1 + 10), box, 2)
        bits = b.bits[i].reshape(b.shape).astype(np.uint8) * 255
        return _png(bits, 4 if b.kind in ("glyph", "money_glyph") else 2)

    def apply_labels(self, labels: dict[tuple[str, int], str]) -> None:
        """{(見本の名前, 番号): ラベル} を付ける。保存は finish_reading() で行う。"""
        by_name = {b.name: b for b in self.banks.values()}
        for (bank_name, i), label in labels.items():
            by_name[bank_name].labels[i] = label


def _extract_all(paths: list[str], template_dir: Path, jobs: int | None, use_processes: bool,
                 progress_callback: ProgressCallback | None) -> list[dict | None]:
    batches = [paths[i:i + EXTRACT_CHUNK] for i in range(0, len(paths), EXTRACT_CHUNK)]
    pool: Executor
    if use_processes:
        pool = ProcessPoolExecutor(jobs, initializer=_init_worker, initargs=(template_dir,))
    else:
        _init_worker(template_dir)
        pool = ThreadPoolExecutor(jobs)
    extracted: list[dict | None] = []
    with pool:
        for batch in pool.map(extract_batch, batches):
            extracted += batch
            if progress_callback:
                progress_callback(len(extracted), len(paths))
    return extracted


def start_reading(
    paths: list[str],
    base_slot: int,
    zenny_step: int,
    minus_skills: dict[str, int] | None = None,
    template_dir: Path = BUNDLED_TEMPLATE_DIR,
    jobs: int | None = None,
    use_processes: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> OcrSession:
    """画像を切り出して見本と照合する（結果はまだ作らない）。

    use_processes=False ではスレッドで切り出す（exe 化したアプリではプロセスを起こせないことがあるため）。
    progress_callback には (切り出しが済んだ枚数, 全枚数) を渡す。
    """
    if not list(signature_dir(template_dir).glob("*.png")):
        raise FileNotFoundError(f"画面判定用の見本がありません: {signature_dir(template_dir)}")
    start = time.perf_counter()
    try:
        extracted = _extract_all(paths, template_dir, jobs, use_processes, progress_callback)
    except BrokenProcessPool:
        # 子プロセスを起こせない環境（__main__ を読み直せない起動のしかたなど）ではスレッドでやり直す
        extracted = _extract_all(paths, template_dir, jobs, False, progress_callback)
    t_extract = time.perf_counter() - start

    session = OcrSession(paths, extracted, base_slot, zenny_step, minus_skills, template_dir)
    for path, ex in zip(paths, extracted):
        if ex is None or ex["screen"] is None:
            session.results.append(None)
            continue
        session.screen_of[path] = ex["screen"]
        ids: dict = {}
        for fld, (kind, packed) in ex["crops"].items():
            b = session.bank(ex["device"], kind)
            key = packed.tobytes()   # 全く同じ切り出しは多いので、照合結果を使い回す
            if key not in b.cache:
                b.cache[key] = b.match(b.unpack(packed), (path, fld))
            ids[fld] = (b, b.cache[key])
        mb = session.bank(ex["device"], "money_glyph")
        ids["money"] = (mb, [mb.cache.setdefault(g.tobytes(), mb.match(mb.unpack(g), (path, "money")))
                             if g.tobytes() not in mb.cache
                             else mb.cache[g.tobytes()] for g in ex["money"]])
        session.results.append(ids)
    t_match = time.perf_counter() - start - t_extract

    session.name_report = {b.name: label_names(b, session.screen_of)
                           for b in list(session.banks.values()) if b.kind == "name"}
    t_ocr = time.perf_counter() - start - t_extract - t_match
    session.build_values()   # 新しい形の文字をここで見つけておく（pending_labels に出すため）
    session.timings = {"extract": t_extract, "match": t_match, "ocr": t_ocr, "start": start}
    return session


def finish_reading(session: OcrSession) -> OcrRun:
    """付いているラベルで結果を作り、見本を保存する。"""
    session.build_values()
    for b in session.banks.values():
        if b.kind == "slot":
            # 追加されたスロット数（"+0"〜"+6"）を手で付ける。未設定のものは要確認にする
            b.labels = [lab or f"?slot#{i}" for i, lab in enumerate(b.labels)]
    for b in session.banks.values():
        b.save()

    # 1 枚ごとの値。ex が None なら読み込み失敗、values が None なら結果画面以外。
    # ラベルが付いていない見本（EasyOCR の無い環境で出た新しいスキル名など）は "?"（要確認）
    records: list[tuple[str, dict | None, dict | None]] = []
    for path, ex, ids in zip(session.paths, session.extracted, session.results):
        values = None
        if ex is not None and ids is not None:
            values = {}
            for c in COLUMNS:
                if c in ids:
                    b, i = ids[c]
                    lab = b.labels[i]
                    values[c] = "?" if lab is None else lab
                else:
                    values[c] = ex["levels"].get(c, "")
            values["slot_base"], values["slot_add"] = str(session.base_slot), values.pop("slot")
            values["cost"] = calc_cost(values)
            money_bank, money_ids = ids["money"]
            values["money_k"] = read_money(money_bank, money_ids)
        records.append((Path(path).name, ex, values))

    report = build_report(records, session.zenny_step // 1000, session.template_dir, session.minus_skills)
    t = session.timings
    timings = {"extract": t["extract"], "match": t["match"], "ocr": t["ocr"],
               "total": time.perf_counter() - t["start"]}
    return OcrRun(report, records, session.paths, session.results, session.screen_of,
                  list(session.banks.values()), session.name_report, session.template_dir, timings)


def read_images(
    paths: list[str],
    base_slot: int,
    zenny_step: int,
    minus_skills: dict[str, int] | None = None,
    template_dir: Path = BUNDLED_TEMPLATE_DIR,
    jobs: int | None = None,
    use_processes: bool = True,
    progress_callback: ProgressCallback | None = None,
) -> OcrRun:
    """画像を読み取り、qurious-crafting-log の取込形式のテキストと自己チェックの結果を返す。

    ラベルが確定していない見本はそのまま（"?"）にする。途中でラベルを付けるときは
    start_reading → apply_labels → finish_reading を使う。新しい見本は template_dir に保存する。
    """
    return finish_reading(start_reading(paths, base_slot, zenny_step, minus_skills, template_dir, jobs,
                                        use_processes, progress_callback))


# ---------------------------------------------------------------- main

def save_signature(layout: str, path: str, template_dir: Path) -> None:
    loaded = load_image(path)
    if loaded is None:
        sys.exit(f"画像を読み込めません: {path}")
    bits = LAYOUTS[layout]["signature"].binarize(loaded[0])
    sig_dir = signature_dir(template_dir)
    sig_dir.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(sig_dir / f"{layout}.png"), bits.astype(np.uint8) * 255)
    print(f"saved {sig_dir / f'{layout}.png'} ({bits.sum()} px)")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("inputs", nargs="*", help="画像ファイルまたはフォルダ")
    parser.add_argument("-o", "--output", default="result.txt", help="出力（回数・ゼニー・スロ・コスト…の形式のテキスト）")
    parser.add_argument("--zenny-step", type=int, choices=(4000, 6000), help="1 回の強化で減るゼニー（使う防具で決まる）")
    parser.add_argument("--detail", metavar="CSV", help="1 枚ごとの詳しい読み取り結果（防御力・画面の種類なども含む）を CSV で出す")
    parser.add_argument("-j", "--jobs", type=int, default=os.cpu_count())
    parser.add_argument("--base-slot", type=int, help="防具の初期スロット（スロット欄のテンプレートをこの値ごとに分ける）")
    parser.add_argument("--slot-sheet", metavar="PNG", help="スロットのテンプレートごとに、ラベル・枚数・実画像の例を並べた確認用画像を書き出す")
    parser.add_argument("--save-signature", nargs=2, metavar=("LAYOUT", "IMAGE"))
    parser.add_argument("--minus-skills", metavar="スキル:元のLv,…",
                        help="防具が元から持つスキルと元のレベル（例: 攻撃:2,火事場力:3）。"
                             "これ以外のスキルが下がった・元のレベルより多く下がったらエラーにする")
    parser.add_argument("--templates", type=Path, default=BUNDLED_TEMPLATE_DIR,
                        help="見本（テンプレート）のフォルダ（既定: 同梱の app/ocr/templates）")
    args = parser.parse_args()

    if args.save_signature:
        layout, image = args.save_signature
        save_signature(layout, image, args.templates)
        return
    if args.base_slot is None:
        parser.error("--base-slot（防具の初期スロット）を指定してください")
    if args.zenny_step is None:
        parser.error("--zenny-step（1 回の強化で減るゼニー: 4000 または 6000）を指定してください")
    try:
        minus_skills = parse_minus_skills(args.minus_skills or "")
    except ValueError:
        parser.error("--minus-skills は「スキル名:元のレベル」をカンマで区切って指定してください（例: 攻撃:2,火事場力:3）")
    if not list(signature_dir(args.templates).glob("*.png")):
        sys.exit("画面判定用の見本がありません。先に --save-signature screen1 <結果画面の画像> を実行してください。")

    run = read_images(list_images(args.inputs), args.base_slot, args.zenny_step, minus_skills,
                      args.templates, args.jobs)

    if args.detail:
        write_detail_csv(args.detail, run.records)
    write_report(args.output, run.report)

    if args.slot_sheet:
        write_slot_sheet(args.slot_sheet, run.paths, run.results, run.screen_of)

    for bank_name, report in run.name_report.items():
        for i, text, label, score in report:
            mark = "??" if score < 0.6 else "  "
            print(f"{mark} {bank_name} #{i:3d} OCR={text!r:20} -> {label} ({score:.2f})")
    for b in run.banks:
        if b.kind in ("slot", "glyph", "money_glyph") and len(b.labels) > b.new_from:
            print(f"新しい{b.kind}テンプレート {len(b.labels) - b.new_from} 個: "
                  f"{run.template_dir / 'review' / b.name} を見て {b.json_path.name} にラベルを書いてください")
    if not easyocr_available() and any(b.kind == "name" and None in b.labels for b in run.banks):
        print("EasyOCR が入っていないため、新しいスキル名の見本にラベルを付けられませんでした（\"?\" になります）",
              file=sys.stderr)
    t = run.timings
    print(
        f"\n{len(run.paths)} 枚 / 画面別 {run.screen_counts} / 結果画面以外 {run.not_result_count}"
        f" / 読込失敗 {run.read_error_count} / 新規テンプレート {run.new_template_count}\n"
        f"切り出し {t['extract']:.1f}s, 照合 {t['match']:.1f}s, OCR {t['ocr']:.1f}s, "
        f"合計 {t['total']:.1f}s -> {args.output}",
        file=sys.stderr,
    )


if __name__ == "__main__":
    main()
