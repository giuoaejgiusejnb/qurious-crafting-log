import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import sqlite3, difflib, collections, os, sys, pickle
sys.stdout.reconfigure(encoding="utf-8")
DB = os.path.join(os.environ["LOCALAPPDATA"], "QuriousCraftingLog", "qurious_crafting_log.db")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
ORDER = {"クシャ胴": ["鋼殻の恩恵", "攻撃", "業物", "弾丸節約"], "ギルパレ脚": ["火事場力", "災禍転福"]}
def load(b):
    label = c.execute("select label from import_batches where id=?", (b,)).fetchone()[0]
    rows = c.execute("select id, zeny_count, slot_add from results where batch_id=? order by zeny_count", (b,)).fetchall()
    sk = collections.defaultdict(list)
    for rid, n, v in c.execute("select rs.result_id, s.name, rs.value from result_skills rs join skills s on s.id=rs.skill_id join results r on r.id=rs.result_id where r.batch_id=?", (b,)):
        sk[rid].append((n, v))
    out = []
    for rid, zc, sa in rows:
        plus = tuple(sorted(n for n, v in sk[rid] if v > 0 and not n.startswith("何らか")))
        minus = tuple(sorted({ORDER[label].index(n) % 2 for n, v in sk[rid] if v < 0 and n in ORDER[label]}))
        out.append(dict(zc=zc, slot=sa, plus=plus, minus=minus, unknown=any(n.startswith("何らか") for n, v in sk[rid]), raw=sk[rid]))
    return out
def key(x): return (x["slot"], x["plus"], x["minus"])
PAIRS = [(33, 32), (34, 35), (36, 37), (53, 54), (55, 56), (48, 49), (66, 65)]  # (ギルパレ, クシャ)
res = {}
for g, k in PAIRS:
    G, K = load(g), load(k)
    sm = difflib.SequenceMatcher(None, [key(x) for x in K], [key(x) for x in G], autojunk=False)
    bl = [m for m in sm.get_matching_blocks() if m.size]
    big = [m for m in bl if m.size >= 6]
    last = big[-1] if big else None
    print(f"ギ#{g}({len(G)}) ク#{k}({len(K)}): 一致 {sum(m.size for m in bl)}件, 6件以上のかたまり {len(big)}個 / {sum(m.size for m in big)}件"
          + (f", 最後のずれ(ク-ギ) {K[last.a]['zc']-G[last.b]['zc']:+d} @ギ#{G[last.b]['zc']}" if last else ""))
    res[(g, k)] = (G, K, bl)
pickle.dump(res, open("pairs.pkl", "wb"))
