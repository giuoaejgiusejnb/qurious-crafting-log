import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import pickle, sys, collections
import numpy as np
sys.stdout.reconfigure(encoding="utf-8")
res = pickle.load(open("pairs.pkl", "rb"))
INIT = {"ギ": {"火事場力", "災禍転福"}, "ク": {"鋼殻の恩恵", "攻撃", "業物", "弾丸節約"}}
def extras(x, init):  # 新しいスキルのうち、クシャ胴なら付けられない 2 個目以降の数
    new = [n for n in x["plus"] if n not in init]
    return max(len(new) - 1, 0)
rows = []
for (gid, kid), (G, K, bl) in res.items():
    if gid == 36: continue
    big = [m for m in bl if m.size >= 6]
    for p, q in zip(big, big[1:]):
        ia, ib = p.a + p.size, p.b + p.size
        la, lb = q.a - ia, q.b - ib
        if la < 0 or lb < 0 or la > 80 or lb > 80: continue
        if K[q.a]["zc"] - K[ia-1]["zc"] != la + 1 or G[q.b]["zc"] - G[ib-1]["zc"] != lb + 1: continue
        if la == 0 and lb == 0: continue
        xg = sum(extras(G[i], INIT["ギ"]) for i in range(ib, q.b))
        xk = sum(extras(K[i], INIT["ク"]) for i in range(ia, q.a))
        rows.append((lb - la, xg, max(la, lb), xk))
R = np.array(rows)
print("区間の数:", len(R))
print("\n区間の中のギルパレ脚の追加スキル数 → ギルパレ脚の遅れ（回）")
print(" 追加数  区間数  遅れの平均  遅れの分布(-2..+4以上)")
for x in range(0, 13):
    s = R[R[:, 1] == x] if x < 12 else R[R[:, 1] >= 12]
    if len(s) == 0: continue
    d = collections.Counter(np.clip(s[:, 0], -2, 4))
    print(f" {x if x<12 else '12+':>5} {len(s):>7} {s[:,0].mean():>10.2f}   " + " ".join(f"{d.get(v,0):>4}" for v in range(-2, 5)))
print("\n区間の長さ（長い方の回数）→ 区間数")
L = collections.Counter(np.minimum(R[:, 2], 30)); print(" ".join(f"{k}:{L[k]}" for k in sorted(L)))
coef = np.polyfit(R[:, 1], R[:, 0], 1)
print("\n遅れ ≈ %.3f × 追加数 + %.3f" % tuple(coef), " 相関", np.corrcoef(R[:,1], R[:,0])[0,1].round(3))
