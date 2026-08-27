import pytest

from app.core.parser import ParseError, parse_result_log_block, parse_result_log_line
from tests.helpers import build_block, build_row


def test_parse_line_with_three_skills():
    line = build_row(
        zeny_count=23,
        zeny=4844,
        slot_add=0,
        total_cost=12,
        deficiency="無",
        resistance=-2,
        skills=[("ＫＯ術", 1), ("精霊の加護", 1), ("属性やられ耐性", 1)],
    )
    result = parse_result_log_line(line)

    assert result.zeny_count == 23
    assert result.zeny == 4844
    assert result.slot_add == 0
    assert result.total_cost == 12
    assert result.has_deficiency == 0
    assert result.print_resistance == -2
    # 全角のＫＯ術は半角KO術に正規化される
    assert [(s.name, s.value) for s in result.skills] == [
        ("KO術", 1),
        ("精霊の加護", 1),
        ("属性やられ耐性", 1),
    ]


def test_parse_line_with_no_skill():
    line = build_row(deficiency="無", resistance=1)
    result = parse_result_log_line(line)
    assert result.skills == []


def test_parse_line_converts_deficiency_flag():
    assert parse_result_log_line(build_row(deficiency="無")).has_deficiency == 0
    assert parse_result_log_line(build_row(deficiency="有")).has_deficiency == 1


def test_parse_line_allows_negative_skill_value():
    line = build_row(deficiency="有", resistance=-5, skills=[("火事場力", -1)])
    result = parse_result_log_line(line)
    assert result.has_deficiency == 1
    assert result.print_resistance == -5
    assert [(s.name, s.value) for s in result.skills] == [("火事場力", -1)]


def test_parse_line_allows_up_to_six_skills():
    skills = [(f"スキル{i}", i) for i in range(1, 7)]
    line = build_row(skills=skills)
    result = parse_result_log_line(line)
    assert len(result.skills) == 6


def test_parse_line_raises_on_wrong_field_count():
    with pytest.raises(ParseError):
        parse_result_log_line("1,2,3")


def test_parse_line_raises_on_non_numeric_field():
    line = build_row()
    broken = line.replace("1,1,0,0", "一,1,0,0", 1)
    with pytest.raises(ParseError):
        parse_result_log_line(broken)


def test_parse_line_raises_on_invalid_deficiency_flag():
    line = build_row().replace(",無,", ",不明,", 1)
    with pytest.raises(ParseError):
        parse_result_log_line(line)


def test_parse_line_raises_on_non_numeric_skill_value():
    fields = build_row(skills=[("攻撃", 1)]).split(",")
    fields[7] = "不正"  # 第1値
    with pytest.raises(ParseError):
        parse_result_log_line(",".join(fields))


def test_parse_block_skips_header_lines():
    row = build_row(zeny_count=1, skills=[("攻撃", 1)])
    text = build_block([row])
    results, errors = parse_result_log_block(text)
    assert len(results) == 1
    assert errors == []


def test_parse_block_separates_valid_and_invalid_lines():
    valid = build_row(zeny_count=1, skills=[("攻撃", 1)])
    invalid = "not,a,valid,row"
    text = build_block([valid, invalid])
    results, errors = parse_result_log_block(text)
    assert len(results) == 1
    assert len(errors) == 1


def test_parse_block_ignores_blank_lines():
    row = build_row(zeny_count=1)
    text = build_block([row, "", row])
    results, errors = parse_result_log_block(text)
    assert len(results) == 2
    assert errors == []


# 実際にユーザーから提供されたサンプルデータ（100行）を使った統合テスト。
REAL_SAMPLE_TEXT = """初期ゼニー,4936
回数,ゼニー,スロ,コスト,マイナス,耐性,第1名,第1値,第2名,第2値,第3名,第3値,第4名,第4値,第5名,第5値,第6名,第6値,対象
1,4932,0,0,無,1,,,,,,,,,,,,,0
2,4928,0,9,無,-5,霞皮の恩恵,1,不屈,1,,,,,,,,,0
3,4924,0,0,無,1,,,,,,,,,,,,,0
4,4920,0,0,無,4,,,,,,,,,,,,,0
5,4916,0,0,有,-5,火事場力,-1,,,,,,,,,,,0
6,4912,0,12,無,-3,睡眠属性強化,1,不屈,1,体力回復量ＵＰ,1,,,,,,,0
7,4908,0,12,無,-3,粉塵纏,1,雷属性攻撃強化,1,,,,,,,,,0
8,4904,0,3,有,0,供応,1,災禍転福,-1,,,,,,,,,0
9,4900,1,18,無,-3,連撃,1,,,,,,,,,,,0
10,4896,2,15,無,-5,陽動,1,,,,,,,,,,,0
11,4892,0,3,無,0,供応,1,,,,,,,,,,,0
12,4888,0,12,無,-3,弱点特効【属性】,1,供応,1,,,,,,,,,0
13,4884,0,9,無,0,チャージマスター,1,,,,,,,,,,,0
14,4880,0,12,無,-5,冰気錬成,1,,,,,,,,,,,0
15,4876,0,9,無,0,弾導強化,1,,,,,,,,,,,0
16,4872,0,0,無,2,,,,,,,,,,,,,0
17,4868,0,3,無,2,腹減り耐性,1,,,,,,,,,,,0
18,4864,0,6,無,-4,体力回復量ＵＰ,1,雷属性攻撃強化,1,,,,,,,,,0
19,4860,1,18,無,0,高速変形,1,,,,,,,,,,,0
20,4856,0,3,無,2,砥石使用高速化,1,,,,,,,,,,,0
21,4852,0,0,無,-1,,,,,,,,,,,,,0
22,4848,0,3,無,-3,スタミナ奪取,1,,,,,,,,,,,0
23,4844,0,12,無,-2,ＫＯ術,1,精霊の加護,1,属性やられ耐性,1,,,,,,,0
24,4840,0,0,無,0,,,,,,,,,,,,,0
25,4836,0,9,無,0,壁面移動,1,泥雪耐性,1,,,,,,,,,0
26,4832,0,0,有,0,災禍転福,-1,,,,,,,,,,,0
27,4828,0,9,無,0,破壊王,1,砥石使用高速化,1,,,,,,,,,0
28,4824,0,0,無,0,,,,,,,,,,,,,0
29,4820,0,9,無,0,鬼火纏,1,,,,,,,,,,,0
30,4816,0,3,無,-3,アイテム使用強化,1,,,,,,,,,,,0
31,4812,0,0,無,2,,,,,,,,,,,,,0
32,4808,1,9,有,-1,広域化,1,災禍転福,-1,,,,,,,,,0
33,4804,0,6,有,0,腹減り耐性,1,滑走強化,1,火事場力,-1,,,,,,,0
34,4800,0,0,有,1,火事場力,-1,,,,,,,,,,,0
35,4796,0,15,有,0,達人芸,1,災禍転福,-1,,,,,,,,,0
36,4792,0,0,無,2,,,,,,,,,,,,,0
37,4788,1,9,無,-3,不屈,1,,,,,,,,,,,0
38,4784,1,12,無,2,ＫＯ術,1,,,,,,,,,,,0
39,4780,0,3,有,-2,腹減り耐性,1,火事場力,-1,,,,,,,,,0
40,4776,0,0,無,-4,,,,,,,,,,,,,0
41,4772,0,3,無,1,陽動,1,,,,,,,,,,,0
42,4768,0,0,無,-3,,,,,,,,,,,,,0
43,4764,0,3,無,2,広域化,1,,,,,,,,,,,0
44,4760,0,3,無,-4,満足感,1,,,,,,,,,,,0
45,4756,0,3,有,-2,毒耐性,1,火事場力,-1,,,,,,,,,0
46,4752,0,3,無,2,満足感,1,,,,,,,,,,,0
47,4748,0,0,無,0,,,,,,,,,,,,,0
48,4744,0,3,無,-1,広域化,1,,,,,,,,,,,0
49,4740,0,0,有,0,火事場力,-1,,,,,,,,,,,0
50,4736,1,18,無,-5,翔蟲使い,1,ひるみ軽減,1,,,,,,,,,0
51,4732,0,9,無,0,反動軽減,1,ひるみ軽減,1,,,,,,,,,0
52,4728,0,12,無,0,剛刃研磨,1,ひるみ軽減,1,,,,,,,,,0
53,4724,0,0,無,0,,,,,,,,,,,,,0
54,4720,1,6,無,1,,,,,,,,,,,,,0
55,4716,0,0,無,0,,,,,,,,,,,,,0
56,4712,0,15,無,0,超会心,1,,,,,,,,,,,0
57,4708,0,6,無,2,陽動,1,睡眠耐性,1,,,,,,,,,0
58,4704,1,9,無,-5,睡眠耐性,1,,,,,,,,,,,0
59,4700,0,3,無,1,陽動,1,,,,,,,,,,,0
60,4696,0,9,無,-3,砲弾装填,1,壁面移動【翔】,1,,,,,,,,,0
61,4692,0,9,無,0,状態異常確定蓄積,1,,,,,,,,,,,0
62,4688,0,6,無,2,睡眠属性強化,1,,,,,,,,,,,0
63,4684,0,0,無,0,,,,,,,,,,,,,0
64,4680,0,3,無,2,腹減り耐性,1,,,,,,,,,,,0
65,4676,0,6,無,2,睡眠属性強化,1,,,,,,,,,,,0
66,4672,0,6,無,3,砲弾装填,1,,,,,,,,,,,0
67,4668,0,15,有,0,装填拡張,1,火事場力,-1,,,,,,,,,0
68,4664,0,0,無,-1,,,,,,,,,,,,,0
69,4660,0,0,無,0,,,,,,,,,,,,,0
70,4656,0,0,無,2,,,,,,,,,,,,,0
71,4652,0,3,無,2,睡眠耐性,1,,,,,,,,,,,0
72,4648,0,9,無,0,強化持続,1,,,,,,,,,,,0
73,4644,0,0,無,1,,,,,,,,,,,,,0
74,4640,0,9,無,2,龍気活性,1,,,,,,,,,,,0
75,4636,0,15,有,0,フルチャージ,1,体力回復量ＵＰ,1,災禍転福,-1,火事場力,-1,,,,,0
76,4632,0,6,無,0,納刀術,1,,,,,,,,,,,0
77,4628,0,12,有,2,死中に活,1,災禍転福,-1,,,,,,,,,0
78,4624,0,3,無,-1,笛吹き名人,1,,,,,,,,,,,0
79,4620,0,3,無,-5,麻痺耐性,1,,,,,,,,,,,0
80,4616,0,12,無,0,冰気錬成,1,,,,,,,,,,,0
81,4612,0,0,無,0,,,,,,,,,,,,,0
82,4608,0,3,無,0,ひるみ軽減,1,,,,,,,,,,,0
83,4604,0,3,無,1,砥石使用高速化,1,,,,,,,,,,,0
84,4600,0,3,無,-5,睡眠耐性,1,,,,,,,,,,,0
85,4596,0,0,有,-6,火事場力,-1,,,,,,,,,,,0
86,4592,0,6,無,4,ガード性能,1,,,,,,,,,,,0
87,4588,0,3,無,0,陽動,1,,,,,,,,,,,0
88,4584,1,6,無,-2,,,,,,,,,,,,,0
89,4580,0,3,無,1,滑走強化,1,,,,,,,,,,,0
90,4576,0,3,無,2,供応,1,,,,,,,,,,,0
91,4572,0,9,無,0,翔蟲使い,1,,,,,,,,,,,0
92,4568,0,0,無,2,,,,,,,,,,,,,0
93,4564,0,3,無,0,不屈,1,,,,,,,,,,,0
94,4560,0,9,無,-3,水属性攻撃強化,1,龍属性攻撃強化,1,スタミナ奪取,1,,,,,,,0
95,4556,0,0,無,4,,,,,,,,,,,,,0
96,4552,0,18,有,0,剛刃研磨,1,麻痺属性強化,1,乗り名人,1,災禍転福,-1,,,,,0
97,4548,0,12,無,-7,渾身,1,,,,,,,,,,,0
98,4544,0,9,無,0,鋼殻の恩恵,1,滑走強化,1,,,,,,,,,0
99,4540,1,9,無,-3,気絶耐性,1,,,,,,,,,,,0
100,4536,0,6,無,2,風圧耐性,1,睡眠耐性,1,,,,,,,,,0"""


def test_real_sample_data_parses_without_errors():
    results, errors = parse_result_log_block(REAL_SAMPLE_TEXT)
    assert errors == []
    assert len(results) == 100


def test_real_sample_data_row5_has_negative_skill_and_deficiency():
    results, _ = parse_result_log_block(REAL_SAMPLE_TEXT)
    row5 = results[4]
    assert row5.zeny_count == 5
    assert row5.has_deficiency == 1  # 有
    assert row5.print_resistance == -5
    assert [(s.name, s.value) for s in row5.skills] == [("火事場力", -1)]


def test_real_sample_data_row75_has_four_skills():
    results, _ = parse_result_log_block(REAL_SAMPLE_TEXT)
    row75 = results[74]
    assert row75.zeny_count == 75
    assert [(s.name, s.value) for s in row75.skills] == [
        ("フルチャージ", 1),
        ("体力回復量UP", 1),  # 全角ＵＰが正規化される
        ("災禍転福", -1),
        ("火事場力", -1),
    ]
