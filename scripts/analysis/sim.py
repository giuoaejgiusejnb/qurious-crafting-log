"""傀異錬成（テーブル6）のシミュレーター。2つの防具が同じ乱数の列（項目の列）を順に使う（見方A）。

規則の決まっていない所は VARIANT で切り替える:
  defgap : 防御力の確率2の欠けた20%の扱い  'norm'=残り80%で割り直す / 'c6'=コスト6・値5の項目とみなす
  stop   : 'six'=いつも6枠 / 'zero'=枠の開始時に残りコストが0以下なら終わる
  seventh: 'none'=7枠目は乱数を使わない / 'scan'=防御力プラス（付けられるもの）が出るまで最大50回引く
  retry  : 1枠の引き直しの上限（既定50）
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import json, random, sys, collections
from app.core.skill_master import SKILL_MASTER

PROPS = json.load(open(os.path.join(_paths.REPO, "app", "ocr", "templates", "skill_props.json"), encoding="utf-8"))
SKILLS_BY_COST = {c: ns for c, ns in SKILL_MASTER}
MAXLV = {n: PROPS.get(n, {}).get("max", 3) for c, ns in SKILL_MASTER for n in ns}

CAT = [("def", 40), ("res", 30), ("slot", 10), ("skill", 20)]
DEF = [(10, (8, 10, 12), 10), (7, (6, 7, 8), 10), (5, (4, 5, 6), 20), (1, (1,), 20), (-3, (-6,), 10), (-5, (-12,), 10)]
RES = [(2, (1, 2), (20, 80), 50), (-2, (-1, -2), (20, 80), 30), (-3, (-3,), (100,), 20)]
SLOT = [(18, 3, 5), (12, 2, 25), (6, 1, 70)]
SKILL = [(15, 8), (12, 14), (9, 18), (6, 20), (3, 30), (-10, 10)]

ARMORS = {
    "ギ": {"火事場力": 2, "災禍転福": 2},
    "ク": {"鋼殻の恩恵": 2, "攻撃": 2, "業物": 2, "弾丸節約": 2},
}


def pick(rng, items, w):
    return rng.choices(items, weights=w)[0]


def make_stream(seed, n, defgap):
    rng = random.Random(seed)
    defs = list(DEF)
    if defgap == "c6":
        defs = defs + [(6, (5,), 20)]
    out = []
    for _ in range(n):
        cat = pick(rng, [c for c, _ in CAT], [w for _, w in CAT])
        if cat == "def":
            cost, vals, _ = pick(rng, defs, [d[2] for d in defs])
            v = vals[0] if len(vals) == 1 else rng.choices(vals, weights=(30, 50, 20))[0]
            out.append(("def", cost, v, None))
        elif cat == "res":
            cost, vals, w, _ = pick(rng, RES, [r[3] for r in RES])
            v = rng.choices(vals, weights=w)[0]
            out.append(("res", cost, v, rng.randrange(5)))
        elif cat == "slot":
            cost, v, _ = pick(rng, SLOT, [s[2] for s in SLOT])
            out.append(("slot", cost, v, None))
        else:
            cost, _ = pick(rng, SKILL, [s[1] for s in SKILL])
            if cost == -10:
                out.append(("minus", -10, -1, rng.randrange(4)))   # n 番目（防具のスキル数で割った余り）
            else:
                out.append(("skill", cost, 1, rng.choice(SKILLS_BY_COST[cost])))
    return out


def craft(stream, pos, init, V):
    """pos から1回練成する。(結果, 新しい pos)"""
    rem = 10
    base = list(init)
    lv = dict(init)                  # 現在のレベル（元から持つスキルを含む）
    plus = collections.Counter(); minus = collections.Counter()
    res = [0] * 5; slot = 0; deff = 0
    for frame in range(6):
        if (V["stop"] == "zero" and rem <= 0) or (V["stop"] == "thr" and rem <= V["thr"]):
            break
        for attempt in range(V["retry"]):
            kind, cost, v, x = stream[pos]; pos += 1
            if cost > rem:
                continue
            if kind == "skill":
                if x not in lv and len(lv) >= 5:
                    continue
                if lv.get(x, 0) + 1 > MAXLV.get(x, 3) + (0 if x not in init else 0):
                    continue
                lv[x] = lv.get(x, 0) + 1; plus[x] += 1
            elif kind == "minus":
                tgt = base[x % len(base)]
                if lv[tgt] - 1 < 0:
                    continue
                lv[tgt] -= 1; minus[tgt] += 1
            elif kind == "res":
                res[x] += v
            elif kind == "slot":
                slot += v
            else:
                deff += v
            rem -= cost
            break
    if V["seventh"] == "scan":
        for attempt in range(V["retry"]):
            kind, cost, v, x = stream[pos]; pos += 1
            if kind == "def" and v > 0 and cost <= rem:
                deff += v; rem -= cost
                break
    deff += max(rem, 0)
    # スキルの増減を合算（同じスキルのプラスとマイナスは打ち消し）
    net = {n: plus[n] - minus[n] for n in set(plus) | set(minus)}
    return dict(slot=slot, net=net, res=tuple(res), deff=deff), pos


def run(init, n_crafts, stream, V):
    pos = 0; out = []
    for _ in range(n_crafts):
        r, pos = craft(stream, pos, init, V)
        out.append(r)
    return out


def to_row(r, init):
    """実データ（pairs.py の load）と同じ形にする"""
    order = list(init)
    raw = [(n, v) for n, v in r["net"].items() if v != 0]
    plus = tuple(sorted(n for n, v in raw if v > 0))
    minus = tuple(sorted({order.index(n) % 2 for n, v in raw if v < 0 and n in order}))
    return dict(slot=r["slot"], plus=plus, minus=minus, raw=raw, res=r["res"], deff=r["deff"], unknown=False)
