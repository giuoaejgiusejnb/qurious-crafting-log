import sqlite3
from dataclasses import dataclass, field

MIN_THRESHOLD = 1
MAX_THRESHOLD = 4

# 並び替え条件。値はSQLのORDER BY句（方向は固定）。
# 「練成順」は、取込バッチが新しい順（＝取込が新しいバッチが先）に並べ、
# 同一バッチ内では練成回数の昇順（1回目→最後）に並べる複合ソート。
SORT_OPTIONS: dict[str, str] = {
    "total_cost_desc": "r.total_cost DESC",
    "craft_order": "r.batch_id DESC, r.zeny_count ASC",
}
DEFAULT_SORT = "craft_order"

# 検索UIのコスト/耐性ドロップダウンの選択肢。設定タブ（防具ごとの初期設定）
# でも同じ選択肢を使うため、ここに集約する。
COST_OPTIONS = [str(n) for n in range(3, 43, 3)]
RESISTANCE_OPTIONS = [str(n) for n in range(-9, 10)]


@dataclass
class SearchParams:
    allowed_skill_ids: list[int] = field(default_factory=list)
    threshold: int = 1
    date_from: str | None = None
    date_to: str | None = None
    batch_id: int | None = None
    label: str | None = None
    min_total_cost: int | None = None
    max_total_cost: int | None = None
    has_deficiency: int | None = None  # 0=無いもののみ, 1=有るもののみ, None=絞り込みなし
    min_resistance: int | None = None
    max_resistance: int | None = None
    sort: str = DEFAULT_SORT
    limit: int = 200
    offset: int = 0

    def __post_init__(self) -> None:
        if not (MIN_THRESHOLD <= self.threshold <= MAX_THRESHOLD):
            raise ValueError(
                f"threshold must be between {MIN_THRESHOLD} and {MAX_THRESHOLD}, got {self.threshold}"
            )
        if self.sort not in SORT_OPTIONS:
            raise ValueError(f"sort must be one of {sorted(SORT_OPTIONS)}, got {self.sort!r}")


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
    has_deficiency: int
    print_resistance: int
    skill_sum: int
    collected: int


_SELECT_COLUMNS = (
    "id, batch_id, imported_at, label, zeny_count, zeny, slot_add, total_cost, "
    "has_deficiency, print_resistance, skill_sum, collected"
)


def search_results(conn: sqlite3.Connection, params: SearchParams) -> list[SearchResultRow]:
    """resultsを検索する（最大 params.limit 件）。並び順はparams.sort（SORT_OPTIONS参照、既定は新しい順）。

    許可スキル集合を指定した場合: そのうちresultが持つ値の合計（＋2は同じスキル2個分として
    加算）がparams.threshold以上のもののみを対象とする。許可集合に含まれないスキルを
    併せ持っていても除外しない（除外はしきい値のみで判定する）。
    result_skills.skill_id にインデックスを張っているため、許可スキル数が少数
    （〜10種類程度）であれば、全件走査ではなくインデックス経由の絞り込みになり高速。

    許可スキル集合を指定しない場合: スキル条件なしで、他の絞り込み条件のみでresultsを検索する。
    """
    select_columns = ", ".join(f"r.{c.strip()}" for c in _SELECT_COLUMNS.split(","))
    query_args: list[object] = []

    if params.allowed_skill_ids:
        placeholders = ",".join("?" * len(params.allowed_skill_ids))
        query_args.extend(params.allowed_skill_ids)
        query = f"""
            SELECT {select_columns}
            FROM (
                SELECT result_id
                FROM result_skills
                WHERE skill_id IN ({placeholders})
                GROUP BY result_id
                HAVING SUM(value) >= ?
            ) matched
            JOIN results r ON r.id = matched.result_id
            WHERE 1 = 1
        """
        query_args.append(params.threshold)
    else:
        query = f"""
            SELECT {select_columns}
            FROM results r
            WHERE 1 = 1
        """

    if params.date_from is not None:
        query += " AND r.imported_at >= ?"
        query_args.append(params.date_from)
    if params.date_to is not None:
        query += " AND r.imported_at <= ?"
        query_args.append(params.date_to)
    if params.batch_id is not None:
        query += " AND r.batch_id = ?"
        query_args.append(params.batch_id)
    if params.label is not None:
        query += " AND r.label = ?"
        query_args.append(params.label)
    if params.min_total_cost is not None:
        query += " AND r.total_cost >= ?"
        query_args.append(params.min_total_cost)
    if params.max_total_cost is not None:
        query += " AND r.total_cost <= ?"
        query_args.append(params.max_total_cost)
    if params.has_deficiency is not None:
        query += " AND r.has_deficiency = ?"
        query_args.append(params.has_deficiency)
    if params.min_resistance is not None:
        query += " AND r.print_resistance >= ?"
        query_args.append(params.min_resistance)
    if params.max_resistance is not None:
        query += " AND r.print_resistance <= ?"
        query_args.append(params.max_resistance)

    query += f" ORDER BY {SORT_OPTIONS[params.sort]} LIMIT ? OFFSET ?"
    query_args.append(params.limit)
    query_args.append(params.offset)

    rows = conn.execute(query, query_args).fetchall()
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


def fetch_distinct_import_dates(conn: sqlite3.Connection) -> list[str]:
    """検索UIの取込日時フィルタ用に、実際に取込が行われた日付（YYYY-MM-DD）の一覧を取得する。"""
    rows = conn.execute(
        "SELECT DISTINCT substr(imported_at, 1, 10) FROM import_batches ORDER BY 1"
    ).fetchall()
    return [r[0] for r in rows]
