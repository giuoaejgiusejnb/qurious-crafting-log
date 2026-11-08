import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, os, random, itertools, collections
sys.stdout.reconfigure(encoding="utf-8")
import sim
from sim import ARMORS, make_stream, run, to_row
COSTOF = {n: c for c, ns in sim.SKILL_MASTER for n in ns}
res = pickle.load(open("pairs.pkl", "rb")); det = pickle.load(open("detail.pkl", "rb"))
def stats(rows, init):
    n = len(rows); cc = collections.Counter()
    for r in rows:
        for s, v in r["raw"]:
            if v > 0: cc[COSTOF.get(s, 0)] += v
            else: cc[-10] += -v
    sk = sum(cc.values()) or 1
    return [sum(len(r["plus"]) for r in rows)/n,
            sum(1 for r in rows if not r["raw"] and r["slot"] == 0)/n,
            sum(1 for r in rows if r["slot"] > 0)/n,
            sum(sum(1 for v in r["res"] if v) for r in rows)/n,
            sum(sum(v for v in r["res"] if v < 0) for r in rows)/n,
            sum(1 for r in rows if any(v < 0 for _, v in r["raw"]))/n,
            sum(1 for r in rows if sum(1 for x in r["plus"] if x not in init) >= 2)/n] + [cc[c]/sk for c in (3, 6, 9, 12, 15, -10)]
NAMES = ["プラス平均", "何も無し", "slot有", "耐性属性数", "耐性マイナス計", "マイナス有", "新2個以上", "c3", "c6", "c9", "c12", "c15", "c-10"]
real = {}
for side in ("ギ", "ク"):
    rows = []
    for (g, k), (G, K, _) in res.items():
        if g == 36: continue
        b, X = (g, G) if side == "ギ" else (k, K)
        for x in X:
            d = det[b].get(x["zc"])
            if d and not x["unknown"]: rows.append(dict(x, res=d["resists"]))
    real[side] = stats(rows, ARMORS[side])
def loss(s, r):
    return sum(((a - b) / (abs(b) + 0.05)) ** 2 for a, b in zip(s, r))
def evaluate(w, V, n=6000, seed=1):
    sim.CAT = list(zip(("def", "res", "slot", "skill"), w))
    st = make_stream(seed, n * 60, V["defgap"])
    L = 0; out = {}
    for side in ("ギ", "ク"):
        rows = [to_row(r, ARMORS[side]) for r in run(ARMORS[side], n, st, V)]
        s = stats(rows, ARMORS[side]); out[side] = s; L += loss(s, real[side])
    return L, out
if __name__ == "__main__":
    rng = random.Random(0)
    best_all = []
    for stop, retry in itertools.product(("six", "zero"), (1, 50)):
        V = dict(defgap="norm", stop=stop, seventh="none", retry=retry)
        best = (1e9, None, None)
        for it in range(70):
            if it == 0: w = (40, 30, 10, 20)
            elif it < 40: w = tuple(rng.randint(1, 60) for _ in range(4))
            else:
                b = best[1]; w = tuple(max(1, x + rng.randint(-6, 6)) for x in b)
            L, out = evaluate(w, V)
            if L < best[0]: best = (L, w, out)
        print(f"{stop}/retry{retry}: 損失 {best[0]:.2f}  カテゴリ(防,耐,ス,スキ)={best[1]}  表どおりの損失 {evaluate((40,30,10,20), V)[0]:.2f}")
        best_all.append((best[0], stop, retry, best[1], best[2]))
    best_all.sort()
    L, stop, retry, w, out = best_all[0]
    print("\n最良:", stop, retry, w)
    for i, nm in enumerate(NAMES):
        print(f"  {nm:<10} 実ギ {real['ギ'][i]:7.3f} 模ギ {out['ギ'][i]:7.3f} | 実ク {real['ク'][i]:7.3f} 模ク {out['ク'][i]:7.3f}")
    pickle.dump(best_all, open("fitcat.pkl", "wb"))
