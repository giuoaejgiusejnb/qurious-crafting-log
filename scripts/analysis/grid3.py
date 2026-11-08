import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, os, itertools
sys.stdout.reconfigure(encoding="utf-8")
import sim2
from sim import ARMORS, to_row
from sync import metrics
from fitcat import stats, real, loss
grid = pickle.load(open("grid.pkl", "rb"))
W = {(thr, retry): w for thr, retry, L, w, m in grid}
def sync_eval(V, seeds=(7, 8, 9)):
    ms = []; L = 0
    for seed in seeds:
        S = sim2.Stream(seed, 8000 * 400)
        G = [to_row(r, ARMORS["ギ"]) for r in sim2.run(ARMORS["ギ"], 8000, S, V)]
        K = [to_row(r, ARMORS["ク"]) for r in sim2.run(ARMORS["ク"], 8000, S, V)]
        ms.append(metrics(G, K))
        if seed == 7: L = loss(stats(G, ARMORS["ギ"]), real["ギ"]) + loss(stats(K, ARMORS["ク"]), real["ク"])
    return L, {k: sum(x[k] for x in ms) / len(ms) for k in ms[0]}
configs = [("乱数複数/全部/残り0", dict(stop="thr", thr=0, mode="full")),
           ("乱数複数/必要分/残り0", dict(stop="thr", thr=0, mode="lazy")),
           ("残り1で外れたら終了/必要分", dict(stop="soft1", mode="lazy"))]
for (name, V), cancel in itertools.product(configs, ("none", "keep", "refund")):
    V = dict(V, retry=50, cat=W[(0, 50)], cancel=cancel)
    L, m = sync_eval(V)
    print(f"{name:<22} 打ち消し:{cancel:<6} 中身の合わなさ{L:5.2f}  " + "  ".join(f"{k} {v:6.3f}" for k, v in m.items()), flush=True)
