from app.core.skill_mask import compute_mask, matches_allowed_set, to_signed64, to_unsigned64

# 許可集合 = {攻撃, 見切り, 弱点特効} をID 0, 1, 2 とする
ATTACK, KIRE, JAKUTEN = 0, 1, 2
OTHER = 3  # 許可集合外のスキル


def allowed_mask():
    return compute_mask([ATTACK, KIRE, JAKUTEN])


def test_signed64_roundtrip_for_high_bit():
    value = 1 << 63  # 符号ビットが立つ値
    signed = to_signed64(value)
    assert signed < 0
    assert to_unsigned64(signed) == value


def test_attack_plus1_kire_plus1_matches():
    lo, hi = compute_mask([ATTACK, KIRE])
    allowed_lo, allowed_hi = allowed_mask()
    assert matches_allowed_set(lo, hi, 2, allowed_lo, allowed_hi) is True


def test_attack_plus2_matches():
    lo, hi = compute_mask([ATTACK])
    allowed_lo, allowed_hi = allowed_mask()
    assert matches_allowed_set(lo, hi, 2, allowed_lo, allowed_hi) is True


def test_attack_plus1_only_does_not_match_sum_below_2():
    lo, hi = compute_mask([ATTACK])
    allowed_lo, allowed_hi = allowed_mask()
    assert matches_allowed_set(lo, hi, 1, allowed_lo, allowed_hi) is False


def test_attack_plus1_with_outside_skill_does_not_match():
    lo, hi = compute_mask([ATTACK, OTHER])
    allowed_lo, allowed_hi = allowed_mask()
    assert matches_allowed_set(lo, hi, 2, allowed_lo, allowed_hi) is False


def test_attack_kire_with_outside_skill_does_not_match():
    lo, hi = compute_mask([ATTACK, KIRE, OTHER])
    allowed_lo, allowed_hi = allowed_mask()
    assert matches_allowed_set(lo, hi, 3, allowed_lo, allowed_hi) is False


def test_high_bit_skill_beyond_64_is_handled_correctly():
    # ビットインデックス64以上（hi側）でも同じロジックが成立することを確認する
    high_skill = 70
    lo, hi = compute_mask([high_skill])
    allowed_lo, allowed_hi = compute_mask([high_skill, ATTACK])
    assert matches_allowed_set(lo, hi, 2, allowed_lo, allowed_hi) is True
