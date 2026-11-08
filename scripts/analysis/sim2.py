"""乱数（0〜1の一様乱数）の列を使い、1つの項目を決めるのに乱数を複数使う版。
mode: 'lazy' = 必要な分だけ（コスト不足は項目まで、上限はスキル名まで決めた時点で判定）
      'full' = 項目の中身（値・属性・スキル名・マイナスの番目）を全部決めてから判定
stop: thr（残りコストがこれ以下なら終わる）/ soft1（0以下で終わり、1のときは次に引いた項目が付けられなければ終わる）
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _paths  # noqa: E402  リポジトリと作業フォルダの場所（作業フォルダに移動する）
import random, collections, sys, os
import sim
from sim import DEF, RES, SLOT, SKILL, SKILLS_BY_COST, MAXLV
COSTOF = {n: c for c, ns in sim.SKILL_MASTER for n in ns}

def choose(u, weights):
    t = u * sum(weights)
    for i, w in enumerate(weights):
        t -= w
        if t < 0: return i
    return len(weights) - 1

class Stream:
    def __init__(self, seed, n):
        r = random.Random(seed); self.u = [r.random() for _ in range(n)]

def draw(S, pos, mode, cat_w, fixed_cat=None):
    """1項目を引く。(コスト, 新しいpos, 残りを引く関数)。fixed_cat があればカテゴリは引かない"""
    u = S.u
    if fixed_cat is None:
        cat = ("def", "res", "slot", "skill")[choose(u[pos], cat_w)]; pos += 1
    else:
        cat = fixed_cat
    if cat == "def":
        i = choose(u[pos], [d[2] for d in DEF]); pos += 1
        cost, vals, _ = DEF[i]
        def rest(pos):
            if len(vals) > 1: v = vals[choose(u[pos], (30, 50, 20))]; pos += 1
            else: v = vals[0]
            return ("def", cost, v, None), pos
    elif cat == "res":
        i = choose(u[pos], [r[3] for r in RES]); pos += 1
        cost, vals, w, _ = RES[i]
        def rest(pos):
            v = vals[choose(u[pos], w)] if len(vals) > 1 else vals[0]
            pos += 1 if len(vals) > 1 else 0
            e = choose(u[pos], (1,)*5); pos += 1
            return ("res", cost, v, e), pos
    elif cat == "slot":
        i = choose(u[pos], [s[2] for s in SLOT]); pos += 1
        cost, v, _ = SLOT[i]
        def rest(pos): return ("slot", cost, v, None), pos
    else:
        i = choose(u[pos], [s[1] for s in SKILL]); pos += 1
        cost = SKILL[i][0]
        def rest(pos):
            if cost == -10:
                n = choose(u[pos], (1,)*4); pos += 1
                return ("minus", -10, -1, n), pos
            names = SKILLS_BY_COST[cost]
            n = names[choose(u[pos], (1,)*len(names))]; pos += 1
            return ("skill", cost, 1, n), pos
    return cost, pos, rest

def craft(S, pos, init, V):
    rem = 10; base = list(init); lv = dict(init)
    plus = collections.Counter(); minus = collections.Counter(); res = [0]*5; slot = 0; deff = 0
    frames = 0
    while frames < 6:
        frames += 1
        if rem <= V.get("thr", 0) and V["stop"] == "thr": break
        if V["stop"] == "soft1" and rem <= 0: break
        accepted = False
        fixed = None
        if V.get("scope") == "item":   # 枠の最初にカテゴリを引き、引き直しは同じカテゴリの中で
            fixed = ("def", "res", "slot", "skill")[choose(S.u[pos], V["cat"])]; pos += 1
        for attempt in range(V["retry"]):
            cost, pos, rest = draw(S, pos, V["mode"], V["cat"], fixed)
            if V["mode"] == "full":
                item, pos = rest(pos)
            if cost > rem:
                ok = False
            else:
                if V["mode"] == "lazy": item, pos = rest(pos)
                kind, cost, v, x = item; ok = True
                if kind == "skill":
                    if (x not in lv and len(lv) >= 5) or lv.get(x, 0) + 1 > MAXLV.get(x, 3): ok = False
                elif kind == "minus":
                    if lv[base[x % len(base)]] - 1 < 0: ok = False
            if not ok:
                if V["stop"] == "soft1" and rem == 1: break   # 残り1で付けられなければ終わり
                continue
            cancel = V.get("cancel", "none")
            if kind == "skill" and cancel != "none" and minus[x] > 0:
                lv[x] += 1; minus[x] -= 1; frames -= 2          # 打ち消し: 2枠とも使わなかったことに
                if cancel == "refund": rem -= 10                  # マイナスで増えた10を戻し、プラスのコストも取らない
                else: rem -= cost
                accepted = True; break
            if kind == "minus" and cancel != "none" and plus[base[x % len(base)]] > 0:
                t = base[x % len(base)]; lv[t] -= 1; plus[t] -= 1; frames -= 2
                if cancel == "refund": rem += COSTOF.get(t, 0)    # プラスで使ったコストを戻す
                else: rem -= cost
                accepted = True; break
            if kind == "skill": lv[x] = lv.get(x, 0) + 1; plus[x] += 1
            elif kind == "minus": t = base[x % len(base)]; lv[t] -= 1; minus[t] += 1
            elif kind == "res": res[x] += v
            elif kind == "slot": slot += v
            else: deff += v
            rem -= cost; accepted = True
            break
        if not accepted and V["stop"] == "soft1" and rem == 1: break
    deff += max(rem, 0)
    net = {n: plus[n] - minus[n] for n in set(plus) | set(minus)}
    return dict(slot=slot, net=net, res=tuple(res), deff=deff), pos

def run(init, n, S, V):
    pos = 0; out = []
    for _ in range(n):
        r, pos = craft(S, pos, init, V); out.append(r)
    return out
