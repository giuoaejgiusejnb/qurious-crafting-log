import re

from app.core.models import ParsedResult, ParsedSkill

FIXED_FIELD_COUNT = 6

_SKILL_TOKEN_RE = re.compile(r"^(?P<name>.+?)(?P<value>[+-]\d+)$")


class ParseError(Exception):
    pass


def parse_result_log_line(line: str) -> ParsedResult:
    line = line.strip()
    if not line:
        raise ParseError("空行です")

    tokens = line.split(",")
    if len(tokens) < FIXED_FIELD_COUNT:
        raise ParseError(f"フィールド数が不足しています（{len(tokens)}個）: {line}")

    fixed_tokens = tokens[:FIXED_FIELD_COUNT]
    skill_tokens = tokens[FIXED_FIELD_COUNT:]

    try:
        zeny_count, zeny, slot_add, total_cost, print_minus, print_resistance = (
            int(t) for t in fixed_tokens
        )
    except ValueError as exc:
        raise ParseError(f"数値への変換に失敗しました: {line}") from exc

    skills: list[ParsedSkill] = []
    for raw_token in skill_tokens:
        token = raw_token.strip()
        if not token:
            continue
        match = _SKILL_TOKEN_RE.match(token)
        if not match:
            raise ParseError(f"スキルの形式が不正です: {token!r}（行全体: {line}）")
        skills.append(ParsedSkill(name=match.group("name"), value=int(match.group("value"))))

    return ParsedResult(
        zeny_count=zeny_count,
        zeny=zeny,
        slot_add=slot_add,
        total_cost=total_cost,
        print_minus=print_minus,
        print_resistance=print_resistance,
        skills=skills,
    )


def parse_result_log_block(text: str) -> tuple[list[ParsedResult], list[tuple[int, str]]]:
    """複数行のresult_logをまとめてパースする。

    戻り値は (パース成功したResultのリスト, [(1始まりの行番号, エラー内容), ...]) のタプル。
    不正な行は例外を送出せずスキップし、エラー一覧として返す。
    """
    results: list[ParsedResult] = []
    errors: list[tuple[int, str]] = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        try:
            results.append(parse_result_log_line(line))
        except ParseError as exc:
            errors.append((line_number, str(exc)))

    return results, errors
