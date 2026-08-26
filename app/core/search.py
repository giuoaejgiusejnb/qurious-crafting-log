import sqlite3
from dataclasses import dataclass, field

from app.core.skill_mask import compute_mask


@dataclass
class SearchParams:
    allowed_skill_ids: list[int] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    batch_id: int | None = None
    label: str | None = None
    min_total_cost: int | None = None
    limit: int = 200


@dataclass
class SearchResultRow:
    id: int
    batch_id: int
    imported_at: str
    label: str | None
    zeny_count: int
    zeny: int
    slot_add: int
    total_cost: int
    print_minus: int
    print_resistance: int
    skill_sum: int


_SELECT_COLUMNS = (
    "id, batch_id, imported_at, label, zeny_count, zeny, slot_add, total_cost, "
    "print_minus, print_resistance, skill_sum"
)


def search_results(conn: sqlite3.Connection, params: SearchParams) -> list[SearchResultRow]:
    """許可スキル集合に含まれるプラススキルのみで構成され、
    合計値が2以上のresultsを検索する（最大 params.limit 件）。

    `(skill_mask & ~allowed_mask) = 0` は「resultの持つスキルが全て許可集合に含まれる」ことを表す。
    JOIN不要・整数演算のみのため、件数が多くても全件走査で現実的な時間に収まる想定（詳細はscripts/benchmark_search.py）。
    """
    allowed_lo, allowed_hi = compute_mask(params.allowed_skill_ids)

    query = f"""
        SELECT {_SELECT_COLUMNS}
        FROM results
        WHERE (skill_mask_lo & ~:allowed_lo) = 0
          AND (skill_mask_hi & ~:allowed_hi) = 0
          AND skill_sum >= 2
    """
    query_params: dict[str, object] = {"allowed_lo": allowed_lo, "allowed_hi": allowed_hi}

    if params.date_from is not None:
        query += " AND imported_at >= :date_from"
        query_params["date_from"] = params.date_from
    if params.date_to is not None:
        query += " AND imported_at <= :date_to"
        query_params["date_to"] = params.date_to
    if params.batch_id is not None:
        query += " AND batch_id = :batch_id"
        query_params["batch_id"] = params.batch_id
    if params.label is not None:
        query += " AND label = :label"
        query_params["label"] = params.label
    if params.min_total_cost is not None:
        query += " AND total_cost >= :min_total_cost"
        query_params["min_total_cost"] = params.min_total_cost

    query += " LIMIT :limit"
    query_params["limit"] = params.limit

    rows = conn.execute(query, query_params).fetchall()
    return [SearchResultRow(*row) for row in rows]


def fetch_skill_breakdown(
    conn: sqlite3.Connection, result_ids: list[int]
) -> dict[int, list[tuple[str, int]]]:
    """検索結果一覧の表示用に、result_idごとのスキル内訳（名前・値）を取得する。"""
    if not result_ids:
        return {}

    placeholders = ",".join("?" * len(result_ids))
    rows = conn.execute(
        f"""
        SELECT rs.result_id, s.name, rs.value
        FROM result_skills rs
        JOIN skills s ON s.id = rs.skill_id
        WHERE rs.result_id IN ({placeholders})
        ORDER BY rs.result_id, s.name
        """,
        result_ids,
    ).fetchall()

    breakdown: dict[int, list[tuple[str, int]]] = {}
    for result_id, name, value in rows:
        breakdown.setdefault(result_id, []).append((name, value))
    return breakdown


def fetch_distinct_labels(conn: sqlite3.Connection) -> list[str]:
    """検索UIの防具フィルタ用に、これまで取込に使われたlabel（防具名）の一覧を取得する。"""
    rows = conn.execute(
        "SELECT DISTINCT label FROM results WHERE label IS NOT NULL ORDER BY label"
    ).fetchall()
    return [r[0] for r in rows]
