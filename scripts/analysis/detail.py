"""読み直した CSV（防御力・耐性入り）を、DB の回数（zeny_count）に結びつける。"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import csv, os, sqlite3, sys, pickle, collections
sys.stdout.reconfigure(encoding="utf-8")
S = _paths.DATA
DB = os.path.join(os.environ["LOCALAPPDATA"], "QuriousCraftingLog", "qurious_crafting_log.db")
c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
RES = ["fire", "water", "thunder", "ice", "dragon"]


def to_int(v):
    return 0 if v in ("-", "", None) else int(v)


def load_detail(bid):
    """{zeny_count: dict(defense, resists, slot_add, skills)}。DB の zeny（千単位）で結びつける"""
    z2n = dict(c.execute("select zeny, zeny_count from results where batch_id=?", (bid,)).fetchall())
    out = {}
    unmatched = 0
    with open(os.path.join(S, "reread", f"b{bid}.csv"), encoding="utf-8-sig") as f:
        for r in csv.DictReader(f):
            if r["screen"] not in ("screen1", "screen2") or not r["money_k"] or "?" in r["money_k"]:
                continue
            n = z2n.get(int(r["money_k"]))
            if n is None:
                unmatched += 1
                continue
            try:
                out[n] = dict(defense=to_int(r["defense"]), resists=tuple(to_int(r[x]) for x in RES),
                              slot=to_int(r["slot_add"]), file=r["file"])
            except ValueError:
                pass  # 読めない値（?）
    return out, unmatched


if __name__ == "__main__":
    allp = {}
    for b in map(int, sys.argv[1:]):
        d, um = load_detail(b)
        n_db = c.execute("select count(*) from results where batch_id=?", (b,)).fetchone()[0]
        # slot の一致で結びつけの正しさを確かめる
        slot_db = dict(c.execute("select zeny_count, slot_add from results where batch_id=?", (b,)).fetchall())
        ok = sum(1 for n, v in d.items() if slot_db.get(n) == v["slot"])
        print(f"#{b}: DB {n_db}件, 結びついた {len(d)}件, 結びつかない {um}枚, スロット一致 {ok}/{len(d)}")
        allp[b] = d
    pickle.dump(allp, open(os.path.join(S, "detail.pkl"), "wb"))
