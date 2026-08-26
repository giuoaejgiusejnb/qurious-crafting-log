import sqlite3
from dataclasses import dataclass, field

from app.core.skill_mask import compute_mask


@dataclass
class SearchParams:
    allowed_skill_ids: list[int] = field(default_factory=list)
    date_from: str | None = None
    date_to: str | None = None
    batch_id: int | None = None
    min_total_cost: int | None = None
    limit: int = 200


@dataclass
class SearchResultRow:
    id: int
    batch_id: int
    imported_at: str
    zeny_count: int
    zeny: int
    slot_add: int
    total_cost: int
    print_minus: int
    print_resistance: int
    skill_sum: int


_SELECT_COLUMNS = (
    "id, batch_id, imported_at, zeny_count, zeny, slot_add, total_cost, "
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
    if params.min_total_cost is not None:
        query += " AND total_cost >= :min_total_cost"
        query_params["min_total_cost"] = params.min_total_cost

    query += " LIMIT :limit"
    query_params["limit"] = params.limit

    rows = conn.execute(query, query_params).fetchall()
    return [SearchResultRow(*row) for row in rows]
