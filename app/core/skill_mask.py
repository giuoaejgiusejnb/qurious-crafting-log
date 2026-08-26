"""スキル集合検索のためのビットマスク計算。

SQLiteのINTEGER列は符号付き64bitで、ビット63が立った値をそのままPythonの
非負整数として渡すとbind時に範囲外になる。そのためDBへ保存・クエリに渡す際は
`to_signed64` で符号付き64bit表現に変換し、SQLite側の `~`（ビットNOT）や `&`
がストレージ側と同じ二の補数表現で計算されるようにする。
"""

BITS_PER_COLUMN = 64
MASK64 = (1 << BITS_PER_COLUMN) - 1


def to_signed64(value: int) -> int:
    value &= MASK64
    if value >= 1 << 63:
        value -= 1 << 64
    return value


def to_unsigned64(value: int) -> int:
    if value < 0:
        value += 1 << 64
    return value & MASK64


def compute_mask(skill_ids: list[int]) -> tuple[int, int]:
    """スキルID（0始まりのビットインデックス）の集合から (lo, hi) の符号付き64bit値を作る。"""
    mask = 0
    for skill_id in skill_ids:
        mask |= 1 << skill_id
    lo = mask & MASK64
    hi = (mask >> BITS_PER_COLUMN) & MASK64
    return to_signed64(lo), to_signed64(hi)


def matches_allowed_set(
    result_mask_lo: int,
    result_mask_hi: int,
    result_skill_sum: int,
    allowed_mask_lo: int,
    allowed_mask_hi: int,
) -> bool:
    """SQL側の検索条件 `(mask & ~allowed) = 0 AND skill_sum >= 2` と同じ判定をPythonで再現する。

    Phase 3のSQLクエリが同じロジックであることをテストで裏付けるためのリファレンス実装。
    """
    lo = to_unsigned64(result_mask_lo) & ~to_unsigned64(allowed_mask_lo) & MASK64
    hi = to_unsigned64(result_mask_hi) & ~to_unsigned64(allowed_mask_hi) & MASK64
    has_disallowed_skill = lo != 0 or hi != 0
    return not has_disallowed_skill and result_skill_sum >= 2
