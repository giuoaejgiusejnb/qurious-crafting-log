"""傀異錬成の抽選の仕様（hyperWiki のテーブル）で、読み取った結果が作れるかを調べる。

仕様:
  - 基礎コストはテーブルで決まる（テーブル 5 = 12、テーブル 6 = 10）
  - 抽選は最大 6 回。1 回ごとに 1 項目を引き、そのコストを使う（同じ項目が何度出てもよい）
  - コストがマイナスの項目は、その分コストが増える。使ったコストの合計は基礎コスト以下
    （マイナスの項目を先に引いたとみなせるので、順番は考えなくてよい）
  - 最後に残ったコストを防御力に変換する（抽選の 6 回とは別）。変換は防御力を上げるだけ
  - 属性耐性は 5 属性のどれかにランダムに付く（同じ属性に何度付いてもよい）
  - スキルは、そのスキルのコストの項目を引くと +1。コスト -10 の項目で防具が元から持つスキルが -1
  - 防具に付くスキルは、元から持つスキルを含めて 5 種類まで（元から持つスキルのレベルが 0 になっても数える）

防御力の値は判定に使わない。テーブル 6 の防御力の項目が実際の抽選と合っておらず、読み取りが正しい結果でも
説明できないものがあるため（防御力を除けば、これまでの全データ 125,369 枚が仕様で作れる）。
ただし、防御力の結果がマイナスなら、防御力マイナスの項目を 1 回以上引いている（変換は防御力を上げるだけなので）。
"""

from __future__ import annotations

from functools import lru_cache

from app.core.skill_master import SKILL_MASTER

MAX_DRAWS = 6
MAX_SKILL_KINDS = 5
SKILL_DOWN_COST = -10
SKILL_COST: dict[str, int] = {name: cost for cost, names in SKILL_MASTER for name in names}
RESISTS = ["fire", "water", "thunder", "ice", "dragon"]

# テーブル番号: (基礎コスト, 防御力の項目のコスト [(コスト, 防御力マイナスか)], 属性耐性の項目 [(コスト, 取りうる値)],
#               スロットの項目 [(コスト, 追加数)])
TABLES: dict[int, tuple[int, list[tuple[int, bool]], list[tuple[int, tuple[int, ...]]], list[tuple[int, int]]]] = {
    5: (12,
        [(12, False), (9, False), (6, False), (5, False), (1, False), (-3, True), (-5, True)],
        [(2, (1, 2)), (-2, (-1, -2)), (-3, (-3,))],
        [(6, 1), (12, 2), (18, 3)]),
    6: (10,
        [(10, False), (7, False), (5, False), (1, False), (-3, True), (-5, True)],
        [(2, (1, 2)), (-2, (-1, -2)), (-3, (-3,))],
        [(6, 1), (12, 2), (18, 3)]),
}


def _to_int(value: str) -> int:
    """読み取った値（"+4" "-12" "-"（変化なし）""）を整数にする。"""
    return 0 if value in ("-", "") else int(value)


class SpecChecker:
    """1 つの抽選テーブルについて、結果が仕様で作れるかを調べる。"""

    def __init__(self, table: int, initial_skills: dict[str, int] | None = None) -> None:
        self.table = table
        self.initial_skills = initial_skills
        self.base, defense_items, resist_items, slot_items = TABLES[table]
        self._resist_draws = [(c, v) for c, vals in resist_items for v in vals]

        # 防御力の引き方 (回数, コスト, 防御力マイナスを引いたか) の集合
        ways = {(0, 0, False)}
        for _ in range(MAX_DRAWS):
            ways |= {(n + 1, cost + c, neg or is_neg) for n, cost, neg in ways if n < MAX_DRAWS
                     for c, is_neg in defense_items}
        self._defense_ways = ways

        # スロットの追加数 s を作る引き方 (回数, コスト) の集合
        self._slot_ways: dict[int, set[tuple[int, int]]] = {0: {(0, 0)}}
        for s in range(1, 3 * MAX_DRAWS + 1):
            self._slot_ways[s] = {(n + 1, cost + c) for c, v in slot_items if v <= s
                                  for n, cost in self._slot_ways[s - v]}

    @property
    def new_skill_limit(self) -> int | None:
        """元から持つスキル以外に付けられるプラスのスキルの種類数。元から持つスキルが分からなければ None。"""
        if self.initial_skills is None:
            return None
        return MAX_SKILL_KINDS - len(self.initial_skills)

    @lru_cache(maxsize=None)
    def _resist_ways(self, total: int, n_left: int) -> frozenset[tuple[int, int]]:
        """1 属性の合計 total を n_left 回以内で作る引き方 (回数, コスト) の集合。"""
        ways = {(0, 0)} if total == 0 else set()
        if n_left > 0:
            for c, v in self._resist_draws:
                for n, cost in self._resist_ways(total - v, n_left - 1):
                    ways.add((n + 1, cost + c))
        return frozenset(ways)

    def _resist_combos(self, resists: list[int]) -> set[tuple[int, int]]:
        combos = {(0, 0)}
        for t in resists:
            ways = self._resist_ways(t, MAX_DRAWS)
            combos = {(a + b, c + d) for a, c in combos for b, d in ways if a + b <= MAX_DRAWS}
        return combos

    def feasible(self, skill_draws: int, skill_cost: int, slot_add: int, resists: list[int], defense: int) -> bool:
        """スキルの抽選 (回数, コスト) と、スロット・耐性・防御力の結果が、仕様で作れるか。"""
        return self._diagnose(skill_draws, skill_cost, slot_add, resists, defense) is None

    def _diagnose(self, skill_draws: int, skill_cost: int, slot_add: int, resists: list[int],
                  defense: int) -> str | None:
        """作れれば None、作れなければ理由。"""
        if skill_draws > MAX_DRAWS:
            return f"スキルのレベルの増減だけで抽選 {skill_draws} 回分（最大 {MAX_DRAWS} 回）"
        slot_ways = self._slot_ways.get(slot_add, set())
        if not slot_ways:
            return f"スロット +{slot_add} は抽選で作れない"
        combos = self._resist_combos(resists)
        if not combos:
            return "耐性の値が抽選の組み合わせで作れない"
        need_negative = defense < 0
        min_draws = MAX_DRAWS + 1
        for ns, c_slot in slot_ways:
            for nr, c_resist in combos:
                left = MAX_DRAWS - skill_draws - ns - nr
                for nd, c_def, neg in self._defense_ways:
                    if nd > left or (need_negative and not neg):
                        continue
                    min_draws = min(min_draws, skill_draws + ns + nr + nd)
                    if skill_cost + c_slot + c_resist + c_def <= self.base:
                        return None
        if min_draws > MAX_DRAWS:
            return f"抽選回数が {MAX_DRAWS} 回を超える"
        return f"コストが足りない（基礎コスト {self.base}）"

    @staticmethod
    def skill_draws_and_cost(skills: list[tuple[str, int]]) -> tuple[int, int]:
        """スキルのレベルの増減から、抽選の回数とコストを求める（プラスはスキルのコスト、マイナスは -10）。"""
        draws = sum(abs(lv) for _, lv in skills)
        cost = sum(lv * SKILL_COST[name] if lv > 0 else -lv * SKILL_DOWN_COST for name, lv in skills)
        return draws, cost

    def violation(self, values: dict[str, str]) -> str | None:
        """読み取った 1 枚分の値（kuijin_ocr の values）が仕様違反なら理由、違反でなければ None。

        スキルがすべて写っている画面（結果画面１）の値を渡す。
        読めていない値（"?"）があるものや、skill_master に無いスキルがあるものは判定しない。
        """
        fields = [values["defense"], values["slot_add"], *(values[r] for r in RESISTS)]
        skills = [(values[f"skill{i}"], values[f"lv{i}"]) for i in (1, 2, 3) if values[f"skill{i}"]]
        if any("?" in v for v in fields) or any("?" in n + lv or n not in SKILL_COST for n, lv in skills):
            return None
        parsed = [(n, int(lv)) for n, lv in skills]

        limit = self.new_skill_limit
        if limit is not None:
            assert self.initial_skills is not None
            new_plus = [n for n, lv in parsed if lv > 0 and n not in self.initial_skills]
            if len(new_plus) > limit:
                return (f"元から持つスキル以外のプラスが {len(new_plus)} 種類（{'・'.join(new_plus)}）で、"
                        f"上限の {limit} 種類を超えている")

        draws, cost = self.skill_draws_and_cost(parsed)
        reason = self._diagnose(draws, cost, int(values["slot_add"]),
                                [_to_int(values[r]) for r in RESISTS], _to_int(values["defense"]))
        return reason


# 結果画面２（4 つ目以降のスキルが写っていない）の、写っていないスキルの判定結果
HIDDEN_ALL_MINUS = "all_minus"     # すべてマイナス
HIDDEN_SOME_MINUS = "some_minus"   # マイナスが 1 個以上（プラスも含まれうる）
HIDDEN_UNKNOWN = "unknown"         # 分からない
HIDDEN_VIOLATION = "violation"     # どう仮定しても仕様で作れない（読み間違いの疑い）


def classify_hidden(values: dict[str, str], initial_skills: dict[str, int] | None,
                    checker: SpecChecker | None) -> str:
    """結果画面２の写っていない 4 つ目以降のスキルが、マイナスかどうかを判定する。

    スキルの表示順は「プラスをコストの高い順（同じコストどうしはランダム）→ マイナス」なので、
    写っていないのは「3 つ目以下のコストのプラス」か「マイナス」。次の順に調べる:
      1. 3 つ目がマイナスなら、写っていないのはすべてマイナス
      2. 元から持つスキル以外のプラスが上限（5 − 元から持つスキルの数）に達していて、
         写っていない元から持つスキルのプラス（コストが 3 つ目以下のもの）も無ければ、すべてマイナス
      3. 写っていない分を「プラス k 個（各 +1）＋写っていない元から持つスキルのマイナス m 回」として
         ありうる組み合わせを抽選の仕様で調べる（checker が無ければ調べない）
           - k >= 1 の組み合わせがどれも作れなければ、すべてマイナス
           - m = 0 の組み合わせがどれも作れなければ、マイナスが 1 個以上
    元から持つスキルが分からないとき・読めていない値があるときは分からない。
    """
    fields = [values["defense"], values["slot_add"], *(values[r] for r in RESISTS)]
    skills = [(values[f"skill{i}"], values[f"lv{i}"]) for i in (1, 2, 3)]
    if initial_skills is None or any("?" in v for v in fields) \
            or any(not n or "?" in n + lv or n not in SKILL_COST for n, lv in skills):
        return HIDDEN_UNKNOWN
    parsed = [(n, int(lv)) for n, lv in skills]
    visible = {n for n, _ in parsed}
    if parsed[2][1] < 0:
        new_left, initial_plus = 0, []   # 並び順から、写っていないプラスは無い
    else:
        third_cost = SKILL_COST[parsed[2][0]]
        new_left = MAX_SKILL_KINDS - len(initial_skills) - sum(
            1 for n, lv in parsed if lv > 0 and n not in initial_skills)
        initial_plus = [n for n in initial_skills if n not in visible and SKILL_COST[n] <= third_cost]
    minus_by_order = new_left <= 0 and not initial_plus
    if checker is None:
        return HIDDEN_ALL_MINUS if minus_by_order else HIDDEN_UNKNOWN
    # 以下、並び順・種類の上限で決まった場合も、マイナスだけの組み合わせが作れるかを確かめる
    # （作れなければ読み間違いの疑い）

    draws, cost = SpecChecker.skill_draws_and_cost(parsed)
    slot_add, defense = int(values["slot_add"]), _to_int(values["defense"])
    resists = [_to_int(values[r]) for r in RESISTS]
    cheapest_new = min(c for c, _ in SKILL_MASTER)   # 元から持つスキル以外のプラスは最も安いコストで仮定する
    plus_possible = minus_free_possible = any_possible = False
    for k_new in range(max(new_left, 0) + 1):
        for mask in range(1 << len(initial_plus)):
            chosen = [initial_plus[j] for j in range(len(initial_plus)) if mask >> j & 1]
            k = k_new + len(chosen)
            plus_cost = k_new * cheapest_new + sum(SKILL_COST[n] for n in chosen)
            pool = sum(lv for n, lv in initial_skills.items() if n not in visible and n not in chosen)
            for m in range(pool + 1):
                if k + m == 0:
                    continue   # 結果画面２なので、写っていないスキルが 1 つ以上ある
                if checker.feasible(draws + k + m, cost + plus_cost + m * SKILL_DOWN_COST, slot_add, resists, defense):
                    any_possible = True
                    plus_possible |= k >= 1
                    minus_free_possible |= m == 0
    if not any_possible:
        return HIDDEN_VIOLATION
    if not plus_possible:
        return HIDDEN_ALL_MINUS
    if not minus_free_possible:
        return HIDDEN_SOME_MINUS
    return HIDDEN_UNKNOWN
