import json
import re
import sqlite3
from dataclasses import dataclass, field

# 画像読み取り（8bit）の自己チェックが出す「結果画面を撮れていない回がある」という知らせ
# （app/ocr/kuijin_ocr.py の check_sequence）。kind='ocr' として保存されるが、同じ欠番は取込のときにも
# 「飛ばされている練成」（kind='skipped'）として記録されるので、エラーとして二重に数えない。
# 前後の画像のファイル名だけを取り出して、「飛ばされている練成」の方に添える
MISSING_SHOT_RE = re.compile(
    r"^\d+回分の画像がありません（撮り忘れの疑い）: (?P<before>.+?)（(?P<before_zeny>\d+)千ゼニー）"
    r"→ (?P<after>.+?)（(?P<after_zeny>\d+)千ゼニー）$"
)
# SQL で同じものを除くための LIKE の形
_MISSING_SHOT_LIKE = "%回分の画像がありません（撮り忘れの疑い）: %"


def is_missing_shot_issue(detail: str) -> bool:
    """画像読み取りの矛盾のうち、欠番の知らせ（「飛ばされている練成」と重なるもの）か。"""
    return MISSING_SHOT_RE.match(detail) is not None


@dataclass
class BatchInfo:
    id: int
    imported_at: str
    label: str | None
    row_count: int
    errors_analyzed: int = 0  # 取込時にエラー検出を行ったか（機能追加前のバッチは0）
    # import_issues の件数（読み込めなかった行 + 飛ばされている練成 + 読み取りの矛盾など。
    # 矛盾のうち欠番の知らせは「飛ばされている練成」と重なるので数えない）
    error_count: int = 0
    source: str = "nx"  # 取込元（nx / 8bit）


def list_batches(conn: sqlite3.Connection) -> list[BatchInfo]:
    rows = conn.execute(
        """
        SELECT b.id, b.imported_at, b.label, b.row_count, b.errors_analyzed,
               (SELECT COUNT(*) FROM import_issues
                WHERE batch_id = b.id AND NOT (kind = 'ocr' AND detail LIKE ?)) AS error_count,
               b.source
        FROM import_batches b
        ORDER BY b.id DESC
        """,
        (_MISSING_SHOT_LIKE,),
    ).fetchall()
    return [BatchInfo(*row) for row in rows]


def delete_batch(conn: sqlite3.Connection, batch_id: int) -> None:
    """指定バッチと、それに属するresults/result_skills/import_issuesを削除する。

    IDの振り直しは行わない（削除後も既存の他バッチ・resultsのIDはそのまま）。
    """
    conn.execute(
        "DELETE FROM result_skills WHERE result_id IN (SELECT id FROM results WHERE batch_id = ?)",
        (batch_id,),
    )
    conn.execute("DELETE FROM results WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM import_issues WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
    conn.commit()


@dataclass
class BatchErrors:
    # (取込テキストの行番号, 判別できれば回数, 理由文)
    unparsable: list[tuple[int, int | None, str]] = field(default_factory=list)
    # 飛ばされている練成 [(練成回数, 推定ゼニー or None), ...]（練成回数の昇順）
    skipped: list[tuple[int, int | None]] = field(default_factory=list)
    # 飛ばされている練成の前後の画像 {練成回数: (前の画像のファイル名, 後の画像のファイル名)}（画像読み取りのバッチだけ）
    skipped_between: dict[int, tuple[str, str]] = field(default_factory=dict)
    # 画像読み取り（8bit）で読めない値があり、取り込めなかった画像 [(練成回数 or None, ゼニー or None, 画像のパス), ...]
    unread: list[tuple[int | None, int | None, str]] = field(default_factory=list)
    # 画像読み取り（8bit）の自己チェックで見つかった矛盾の内容
    ocr: list[str] = field(default_factory=list)
    # 画像読み取り（8bit）の結果が抽選の仕様で作れないもの（読み間違いの疑い）の内容
    spec: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.unparsable) + len(self.skipped) + len(self.unread) + len(self.ocr) + len(self.spec)


def fetch_batch_errors(conn: sqlite3.Connection, batch_id: int) -> BatchErrors:
    """バッチの取込時に検出した問題（読み込めなかった行・飛ばされている練成・読み取りの矛盾）を返す。"""
    rows = conn.execute(
        """
        SELECT kind, line_number, zeny_count, detail
        FROM import_issues
        WHERE batch_id = ?
        ORDER BY kind, COALESCE(line_number, zeny_count), id
        """,
        (batch_id,),
    ).fetchall()

    errors = BatchErrors()
    gaps: list[tuple[int, int, str, str]] = []   # 欠番の知らせ（前のゼニー, 後のゼニー, 前の画像, 後の画像）
    for kind, line_number, zeny_count, detail in rows:
        if kind == "unparsable":
            errors.unparsable.append((line_number, zeny_count, detail or ""))
        elif kind == "skipped":
            zeny = int(detail) if detail is not None else None
            errors.skipped.append((zeny_count, zeny))
        elif kind == "unread":
            info = json.loads(detail or "{}")
            errors.unread.append((zeny_count, info.get("zeny"), info.get("path", "")))
        elif kind == "ocr":
            gap = MISSING_SHOT_RE.match(detail or "")
            if gap is None:
                errors.ocr.append(detail or "")
            else:
                gaps.append((int(gap["before_zeny"]), int(gap["after_zeny"]), gap["before"], gap["after"]))
        elif kind == "spec":
            errors.spec.append(detail or "")
    errors.skipped.sort()
    # 欠番のゼニーは、前後の画像のゼニーの間にある
    for count, zeny in errors.skipped:
        between = next(((b, a) for bz, az, b, a in gaps if zeny is not None and az < zeny < bz), None)
        if between is not None:
            errors.skipped_between[count] = between
    return errors


@dataclass
class BatchResultRow:
    id: int
    zeny_count: int
    zeny: int
    slot_add: int
    total_cost: int
    has_deficiency: int
    print_resistance: int
    skill_sum: int


def fetch_batch_results(
    conn: sqlite3.Connection, batch_id: int, limit: int = 200, offset: int = 0
) -> list[BatchResultRow]:
    rows = conn.execute(
        """
        SELECT id, zeny_count, zeny, slot_add, total_cost, has_deficiency, print_resistance, skill_sum
        FROM results
        WHERE batch_id = ?
        ORDER BY id
        LIMIT ? OFFSET ?
        """,
        (batch_id, limit, offset),
    ).fetchall()
    return [BatchResultRow(*row) for row in rows]
