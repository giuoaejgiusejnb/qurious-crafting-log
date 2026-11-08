import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, os, difflib, collections
sys.stdout.reconfigure(encoding="utf-8")
import sim2
from sim import ARMORS, to_row
from sync import key
INIT = {"ギ": set(ARMORS["ギ"]), "ク": set(ARMORS["ク"])}
def cls(g, k):
    pg, pk = set(g["plus"]), set(k["plus"])
    t = []
    if pk < pg: t.append("ギ追加")
    elif pg < pk: t.append("ク追加")
    elif pg != pk: t.append("プラス別")
    if g["slot"] != k["slot"]: t.append("slot違い")
    if g["minus"] != k["minus"]: t.append("マイナス違い")
    return "+".join(t) or "スキル・slot・マイナス同じ"
def tally(G, K, C):
    sm = difflib.SequenceMatcher(None, [key(x) for x in K], [key(x) for x in G], autojunk=False)
    big = [m for m in sm.get_matching_blocks() if m.size >= 6]
    for p, q in zip(big, big[1:]):
        ia, ib = p.a + p.size, p.b + p.size; la, lb = q.a - ia, q.b - ib
        if la < 1 or lb < 1 or la > 80 or lb > 80: continue
        typ = "先行" if lb < la else ("遅れ" if lb > la else "ずれ無し")
        C[typ][cls(G[ib], K[ia])] += 1
def show(name, C):
    print("==", name)
    for typ in ("先行", "遅れ", "ずれ無し"):
        tot = sum(C[typ].values())
        print(f"  ギ{typ} {tot}区間: " + ", ".join(f"{k} {v/tot:.0%}" for k, v in C[typ].most_common(5)))
if __name__ == "__main__":   # scope.py が cls を import するので、計算は直接実行したときだけ
    C = collections.defaultdict(collections.Counter)
    res = pickle.load(open("pairs.pkl", "rb"))
    for (g, k), (G, K, _) in res.items():
        if g != 36: tally(G, K, C)
    show("実データ", C)
    grid = pickle.load(open("grid.pkl", "rb")); W = {(t, r): w for t, r, L, w, m in grid}
    V = dict(stop="thr", thr=0, mode="full", retry=50, cat=W[(0, 50)], cancel="keep")
    C = collections.defaultdict(collections.Counter)
    for seed in (7, 8, 9):
        S = sim2.Stream(seed, 8000 * 400)
        G = [to_row(r, ARMORS["ギ"]) for r in sim2.run(ARMORS["ギ"], 8000, S, V)]
        K = [to_row(r, ARMORS["ク"]) for r in sim2.run(ARMORS["ク"], 8000, S, V)]
        tally(G, K, C)
    show("シミュレーター（乱数複数・全部決めてから・残り0）", C)
