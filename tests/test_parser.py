import pytest

from app.core.parser import ParseError, parse_result_log_block, parse_result_log_line


def test_parse_line_with_two_skills():
    result = parse_result_log_line("5,120,1,500,0,0,攻撃+1,見切り+1")
    assert result.zeny_count == 5
    assert result.zeny == 120
    assert result.slot_add == 1
    assert result.total_cost == 500
    assert result.print_minus == 0
    assert result.print_resistance == 0
    assert [(s.name, s.value) for s in result.skills] == [("攻撃", 1), ("見切り", 1)]


def test_parse_line_with_one_skill():
    result = parse_result_log_line("5,120,1,500,0,0,攻撃+2")
    assert [(s.name, s.value) for s in result.skills] == [("攻撃", 2)]


def test_parse_line_with_no_skill():
    result = parse_result_log_line("5,120,1,500,0,0")
    assert result.skills == []


def test_parse_line_strips_whitespace_and_newline():
    result = parse_result_log_line("  5,120,1,500,0,0,攻撃+1  \n")
    assert result.zeny_count == 5
    assert [(s.name, s.value) for s in result.skills] == [("攻撃", 1)]


def test_parse_line_raises_on_missing_fields():
    with pytest.raises(ParseError):
        parse_result_log_line("5,120,1,500")


def test_parse_line_raises_on_non_numeric_field():
    with pytest.raises(ParseError):
        parse_result_log_line("五,120,1,500,0,0,攻撃+1")


def test_parse_line_raises_on_malformed_skill_token():
    with pytest.raises(ParseError):
        parse_result_log_line("5,120,1,500,0,0,攻撃")


def test_parse_block_separates_valid_and_invalid_lines():
    text = "\n".join(
        [
            "5,120,1,500,0,0,攻撃+1,見切り+1",
            "",
            "invalid,line",
            "5,120,1,500,0,0,攻撃+2",
        ]
    )
    results, errors = parse_result_log_block(text)
    assert len(results) == 2
    assert len(errors) == 1
    assert errors[0][0] == 3  # 空行を除いた実際の行番号（1始まり）
