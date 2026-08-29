import sqlite3
from dataclasses import dataclass


@dataclass
class BatchInfo:
    id: int
    imported_at: str
    label: str | None
    row_count: int


def list_batches(conn: sqlite3.Connection) -> list[BatchInfo]:
    rows = conn.execute(
        "SELECT id, imported_at, label, row_count FROM import_batches ORDER BY id DESC"
    ).fetchall()
    return [BatchInfo(*row) for row in rows]


def delete_batch(conn: sqlite3.Connection, batch_id: int) -> None:
    """指定バッチと、それに属するresults/result_skillsを削除する。

    IDの振り直しは行わない（削除後も既存の他バッチ・resultsのIDはそのまま）。
    """
    conn.execute(
        "DELETE FROM result_skills WHERE result_id IN (SELECT id FROM results WHERE batch_id = ?)",
        (batch_id,),
    )
    conn.execute("DELETE FROM results WHERE batch_id = ?", (batch_id,))
    conn.execute("DELETE FROM import_batches WHERE id = ?", (batch_id,))
    conn.commit()


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
