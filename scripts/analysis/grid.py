import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, os, random, itertools
sys.stdout.reconfigure(encoding="utf-8")
import sim
from sim import ARMORS, make_stream, run, to_row
from fitcat import evaluate
from sync import metrics
def fit(V, start, rng, n_iter=45):
    best = (evaluate(start, V)[0], start)
    for it in range(n_iter):
        b = best[1]
        w = tuple(max(1, x + rng.randint(-8, 8)) for x in b) if it % 3 else tuple(rng.randint(1, 70) for _ in range(4))
        L = evaluate(w, V)[0]
        if L < best[0]: best = (L, w)
    return best
rng = random.Random(0)
out = []
for thr, retry in itertools.product((0, 1, 2, 3), (20, 50, 100)):
    V = dict(defgap="norm", stop="thr", thr=thr, seventh="none", retry=retry)
    L, w = fit(V, (53, 26, 7, 29), rng)
    sim.CAT = list(zip(("def", "res", "slot", "skill"), w))
    ms = []
    for seed in (7, 8):
        st = make_stream(seed, 8000 * 80, "norm")
        G = [to_row(r, ARMORS["ギ"]) for r in run(ARMORS["ギ"], 8000, st, V)]
        K = [to_row(r, ARMORS["ク"]) for r in run(ARMORS["ク"], 8000, st, V)]
        ms.append(metrics(G, K))
    m = {k: sum(x[k] for x in ms) / 2 for k in ms[0]}
    print(f"残り{thr}以下で終了/引き直し{retry:>3}  合わなさ{L:5.2f} 率{w}  " + "  ".join(f"{k} {v:6.3f}" for k, v in m.items()), flush=True)
    out.append((thr, retry, L, w, m))
pickle.dump(out, open("grid.pkl", "wb"))
