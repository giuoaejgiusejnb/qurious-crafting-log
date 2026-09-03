import unicodedata

from app.core.models import ParsedResult, ParsedSkill

FIXED_FIELD_COUNT = 6  # 回数,ゼニー,スロ,コスト,マイナス,耐性
SKILL_SLOT_COUNT = 6  # 第1〜第6の(名前,値)ペア
# 6固定列 + スキル6枠(名前・値のペア) + 対象列(使用しない)
EXPECTED_FIELD_COUNT = FIXED_FIELD_COUNT + SKILL_SLOT_COUNT * 2 + 1

# 入力CSVの「マイナス」列は「無」「有」のフラグ。
# 実態はスキル欠け（マイナス値のスキルを含むかどうか）を表すため、
# コード・画面表示上は「スキル欠け」として扱う（0=無, 1=有）。
_FLAG_VALUES = {"無": 0, "有": 1}

_INITIAL_ZENY_PREFIX = "初期ゼニー"
_HEADER_PREFIX = "回数"


class ParseError(Exception):
    pass


def _skip_leading_header_lines(lines: list[str]) -> list[str]:
    """先頭の「初期ゼニー,####」行と、見出し行（回数,ゼニー,...）をスキップする。"""
    remaining = list(lines)
    if remaining and remaining[0].strip().startswith(_INITIAL_ZENY_PREFIX):
        remaining = remaining[1:]
    if remaining and remaining[0].strip().startswith(_HEADER_PREFIX):
        remaining = remaining[1:]
    return remaining


def parse_result_log_line(line: str) -> ParsedResult:
    """1行分のCSV形式result_logをパースする。

    列構成: 回数,ゼニー,スロ,コスト,マイナス,耐性,第1名,第1値,...,第6名,第6値,対象
    - マイナス列は「無」「有」で、スキル欠けの有無として0/1で保存する
    - 耐性列は数値（マイナス値もありうる）
    - スキルが無い枠は名前が空文字になる
    - スキル値は正負どちらもありうる（そのまま記録する）
    - 対象列は使用しない
    """
    line = line.strip()
    if not line:
        raise ParseError("空行です")

    fields = line.split(",")
    if len(fields) != EXPECTED_FIELD_COUNT:
        raise ParseError(
            f"フィールド数が不正です（{len(fields)}個、期待値{EXPECTED_FIELD_COUNT}個）\n"
            f"（行全体: {line}）"
        )

    try:
        zeny_count = int(fields[0])
        zeny = int(fields[1])
        slot_add = int(fields[2])
        total_cost = int(fields[3])
    except ValueError as exc:
        raise ParseError(f"数値への変換に失敗しました\n（行全体: {line}）") from exc

    deficiency_raw = fields[4].strip()
    if deficiency_raw not in _FLAG_VALUES:
        raise ParseError(
            f"マイナス（スキル欠け）列の値が不正です（'無'または'有'を期待）: {deficiency_raw!r}\n"
            f"（行全体: {line}）"
        )
    has_deficiency = _FLAG_VALUES[deficiency_raw]

    try:
        print_resistance = int(fields[5])
    except ValueError as exc:
        raise ParseError(
            f"耐性列の値の変換に失敗しました: {fields[5]!r}\n（行全体: {line}）"
        ) from exc

    skills: list[ParsedSkill] = []
    for slot in range(SKILL_SLOT_COUNT):
        name_index = FIXED_FIELD_COUNT + slot * 2
        value_index = name_index + 1
        raw_name = fields[name_index].strip()
        raw_value = fields[value_index].strip()
        if not raw_name:
            continue
        try:
            value = int(raw_value)
        except ValueError as exc:
            # 空欄と「読めない値」を区別できるように表示する。repr の '' は
            # ダブルクォート1つに見誤りやすいため使わない。
            value_display = f"「{raw_value}」" if raw_value else "（空欄）"
            raise ParseError(
                f"スキル値の変換に失敗しました: {raw_name}={value_display}\n（行全体: {line}）"
            ) from exc
        # 実データは全角（例: ＫＯ術）で出力されるため、マスターの半角表記に合わせて正規化する
        normalized_name = unicodedata.normalize("NFKC", raw_name)
        skills.append(ParsedSkill(name=normalized_name, value=value))

    return ParsedResult(
        zeny_count=zeny_count,
        zeny=zeny,
        slot_add=slot_add,
        total_cost=total_cost,
        has_deficiency=has_deficiency,
        print_resistance=print_resistance,
        skills=skills,
    )


def parse_result_log_block(text: str) -> tuple[list[ParsedResult], list[tuple[int, str]]]:
    """複数行のresult_logをまとめてパースする。

    先頭の「初期ゼニー」行・見出し行は自動的にスキップする。
    戻り値は (パース成功したResultのリスト, [(1始まりの行番号, エラー内容), ...]) のタプル。
    不正な行は例外を送出せずスキップし、エラー一覧として返す。
    """
    all_lines = text.splitlines()
    data_lines = _skip_leading_header_lines(all_lines)
    skipped_count = len(all_lines) - len(data_lines)

    results: list[ParsedResult] = []
    errors: list[tuple[int, str]] = []

    for offset, line in enumerate(data_lines, start=1):
        if not line.strip():
            continue
        line_number = offset + skipped_count
        try:
            results.append(parse_result_log_line(line))
        except ParseError as exc:
            errors.append((line_number, str(exc)))

    return results, errors
