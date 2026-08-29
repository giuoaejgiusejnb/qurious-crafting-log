import sqlite3
from dataclasses import dataclass

MAX_COLLECTED = 200


class CollectionLimitError(Exception):
    """回収チェック済み件数がMAX_COLLECTEDを超える場合に送出する。"""


def count_collected(conn: sqlite3.Connection, batch_id: int) -> int:
    """指定バッチ内で回収チェック済みのresults件数を返す（上限はバッチごとに独立）。"""
    return conn.execute(
        "SELECT COUNT(*) FROM results WHERE batch_id = ? AND collected = 1", (batch_id,)
    ).fetchone()[0]


def set_collected(conn: sqlite3.Connection, result_id: int, batch_id: int, collected: bool) -> None:
    """指定したresultの回収チェック状態を更新する。

    チェックを付ける操作で、そのresultが属するバッチ内の回収チェック済み件数が
    MAX_COLLECTEDを超える場合はCollectionLimitErrorを送出し、更新は行わない
    （上限はバッチごとに独立しており、他バッチとは共有しない）。
    既にチェック済みのものへ再度チェックしようとした場合は上限チェックをスキップする
    （件数が増えるわけではないため）。
    """
    if collected:
        row = conn.execute("SELECT collected FROM results WHERE id = ?", (result_id,)).fetchone()
        already_collected = bool(row and row[0])
        if not already_collected and count_collected(conn, batch_id) >= MAX_COLLECTED:
            raise CollectionLimitError(
                f"回収にチェックマークをつけることができるのは{MAX_COLLECTED}件までです"
            )

    conn.execute(
        "UPDATE results SET collected = ? WHERE id = ?",
        (1 if collected else 0, result_id),
    )
    conn.commit()


@dataclass
class CollectedResultRow:
    id: int
    zeny_count: int
    zeny: int
    slot_add: int
    total_cost: int
    has_deficiency: int
    print_resistance: int
    skill_sum: int


def fetch_collected_in_batch(
    conn: sqlite3.Connection, batch_id: int, limit: int = MAX_COLLECTED, offset: int = 0
) -> list[CollectedResultRow]:
    """指定バッチ内で回収チェック済みのresultsを練成回数順に取得する。

    回収チェック済みの総件数はMAX_COLLECTED以下に制限されているため、
    1バッチ分であってもページングは不要（既定のlimitで足りる）。
    """
    rows = conn.execute(
        """
        SELECT id, zeny_count, zeny, slot_add, total_cost, has_deficiency, print_resistance, skill_sum
        FROM results
        WHERE batch_id = ? AND collected = 1
        ORDER BY zeny_count
        LIMIT ? OFFSET ?
        """,
        (batch_id, limit, offset),
    ).fetchall()
    return [CollectedResultRow(*row) for row in rows]
