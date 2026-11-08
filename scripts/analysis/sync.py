import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, os, difflib, collections
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")
import sim
from sim import ARMORS, make_stream, run, to_row
INIT_G = set(ARMORS["ギ"])
def key(x): return (x["slot"], x["plus"], x["minus"])
def metrics(G, K):
    sm = difflib.SequenceMatcher(None, [key(x) for x in K], [key(x) for x in G], autojunk=False)
    bl = [m for m in sm.get_matching_blocks() if m.size]
    big = [m for m in bl if m.size >= 6]
    last = big[-1]
    delay = (last.b - last.a) / last.b      # 並びの番号で（欠番は無視できるほど少ない）
    match = sum(m.size for m in bl) / len(K)
    xs, ds, once, ahead, nwin = [], [], 0, 0, 0
    for p, q in zip(big, big[1:]):
        ia, ib = p.a + p.size, p.b + p.size
        la, lb = q.a - ia, q.b - ib
        if la > 80 or lb > 80 or (la == 0 and lb == 0): continue
        nwin += 1
        xg = sum(max(sum(1 for n in G[i]["plus"] if n not in INIT_G) - 1, 0) for i in range(ib, q.b))
        xs.append(xg); ds.append(lb - la)
        once += (la == lb == 1); ahead += (lb < la)
    slope = np.polyfit(xs, ds, 1)[0]
    return dict(遅れ=delay, 一致率=match, 区間数1千回あたり=1000 * nwin / len(K), 傾き=slope, 一回だけ=once / nwin, ギ先行=ahead / nwin)
def show(name, m): print(f"{name:<34}" + "  ".join(f"{k} {v:6.3f}" for k, v in m.items()))
if __name__ == "__main__":
    if "real" in sys.argv:
        res = pickle.load(open("pairs.pkl", "rb"))
        for (g, k), (G, K, _) in res.items():
            if g == 36: continue
            show(f"実データ ギ#{g}/ク#{k}", metrics(G, K))
    else:
        best_all = pickle.load(open("fitcat.pkl", "rb"))
        for L, stop, retry, w, _ in best_all:
            for seventh in ("none", "scan"):
                V = dict(defgap="norm", stop=stop, seventh=seventh, retry=retry)
                sim.CAT = list(zip(("def", "res", "slot", "skill"), w))
                st = make_stream(7, 8000 * 80, "norm")
                G = [to_row(r, ARMORS["ギ"]) for r in run(ARMORS["ギ"], 8000, st, V)]
                K = [to_row(r, ARMORS["ク"]) for r in run(ARMORS["ク"], 8000, st, V)]
                show(f"{stop}/retry{retry}/7枠目{seventh}", metrics(G, K))
