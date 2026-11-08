"""引き直しの範囲（カテゴリから / 枠ごとにカテゴリを固定）を比べる。
版ごとにカテゴリの抽選率を 1 回の練成の中身に合わせ直してから、ずれの統計と、食い違いの始まりの中身を測る。
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402
import itertools, random, collections, difflib, pickle
sys.stdout.reconfigure(encoding="utf-8")
import sim2
from sim import ARMORS, to_row
from sync import metrics, key
from fitcat import stats, real, loss
from aheadcmp import cls


def ev(w, V, n=6000):
    S = sim2.Stream(1, n * 600); L = 0
    for side in ("ギ", "ク"):
        rows = [to_row(r, ARMORS[side]) for r in sim2.run(ARMORS[side], n, S, dict(V, cat=w))]
        L += loss(stats(rows, ARMORS[side]), real[side])
    return L


def fit(V, start, rng, n_iter=50):
    best = (ev(start, V), start)
    for it in range(n_iter):
        w = tuple(max(1, x + rng.randint(-8, 8)) for x in best[1]) if it % 3 else tuple(rng.randint(1, 70) for _ in range(4))
        L = ev(w, V)
        if L < best[0]: best = (L, w)
    return best


def slot_diff_share(G, K):
    sm = difflib.SequenceMatcher(None, [key(x) for x in K], [key(x) for x in G], autojunk=False)
    big = [m for m in sm.get_matching_blocks() if m.size >= 6]
    c = collections.Counter()
    for p, q in zip(big, big[1:]):
        ia, ib = p.a + p.size, p.b + p.size
        if q.a - ia < 1 or q.b - ib < 1: continue
        c["slot違い" in cls(G[ib], K[ia])] += 1
    return c[True] / max(sum(c.values()), 1)


if __name__ == "__main__":
    rng = random.Random(0)
    print("実データ: 遅れ 4.3〜5.4%  一致率 47〜51%  追加1個あたり 0.24〜0.43  1回だけ 2〜8%  ギ先行 21〜26%  始まりでslot違い 11〜15%")
    for scope, mode in itertools.product(("cat", "item"), ("full", "lazy")):
        V = dict(stop="thr", thr=0, retry=50, mode=mode, scope=scope, cancel="keep")
        L0 = ev((40, 30, 10, 20), V)
        L, w = fit(V, (40, 30, 10, 20), rng)
        V = dict(V, cat=w)
        ms, sd = [], []
        for seed in (7, 8, 9):
            S = sim2.Stream(seed, 8000 * 600)
            G = [to_row(r, ARMORS["ギ"]) for r in sim2.run(ARMORS["ギ"], 8000, S, V)]
            K = [to_row(r, ARMORS["ク"]) for r in sim2.run(ARMORS["ク"], 8000, S, V)]
            ms.append(metrics(G, K)); sd.append(slot_diff_share(G, K))
        m = {k: sum(x[k] for x in ms) / 3 for k in ms[0]}
        print(f"範囲{scope}/{mode}: 表どおりの合わなさ {L0:.2f} → 合わせ後 {L:.2f} 率{w}  "
              + "  ".join(f"{k} {v:.3f}" for k, v in m.items()) + f"  始まりでslot違い {sum(sd)/3:.3f}", flush=True)
