import sqlite3
from dataclasses import dataclass, field


@dataclass
class BatchInfo:
    id: int
    imported_at: str
    label: str | None
    row_count: int
    errors_analyzed: int = 0  # 取込時にエラー検出を行ったか（機能追加前のバッチは0）
    error_count: int = 0  # import_issues の件数（読み込めなかった行 + 飛ばされている練成）


def list_batches(conn: sqlite3.Connection) -> list[BatchInfo]:
    rows = conn.execute(
        """
        SELECT b.id, b.imported_at, b.label, b.row_count, b.errors_analyzed,
               (SELECT COUNT(*) FROM import_issues WHERE batch_id = b.id) AS error_count
        FROM import_batches b
        ORDER BY b.id DESC
        """
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

    @property
    def total(self) -> int:
        return len(self.unparsable) + len(self.skipped)


def fetch_batch_errors(conn: sqlite3.Connection, batch_id: int) -> BatchErrors:
    """バッチの取込時に検出した問題（読み込めなかった行・飛ばされている練成）を返す。"""
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
    for kind, line_number, zeny_count, detail in rows:
        if kind == "unparsable":
            errors.unparsable.append((line_number, zeny_count, detail or ""))
        elif kind == "skipped":
            zeny = int(detail) if detail is not None else None
            errors.skipped.append((zeny_count, zeny))
    errors.skipped.sort()
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
