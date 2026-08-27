"""スキル集合検索のベンチマークスクリプト。

大量のダミーデータをDBへ直接生成し、search_results()の実行時間を計測する。
result_log→パース経由ではなく、results/skillsテーブルへ直接ビットマスクを
書き込むことで、10万〜1,000万件規模のデータ生成自体を高速に行う。

使い方:
    .venv/Scripts/python.exe scripts/benchmark_search.py 1000000
    .venv/Scripts/python.exe scripts/benchmark_search.py 10000000 --db-path data/bench.db
"""

import argparse
import random
import sqlite3
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.search import SearchParams, search_results  # noqa: E402
from app.core.skill_mask import compute_mask  # noqa: E402
from app.db.connection import get_connection  # noqa: E402

SKILL_COUNT = 80  # スキル総数100種類未満という想定を模擬
CHUNK_SIZE = 20_000
ALLOWED_SKILL_COUNT = 10  # 検索時に許可するスキル集合の要素数の想定


def generate_dummy_data(
    conn: sqlite3.Connection, row_count: int, guaranteed_match_count: int = 30
) -> int:
    """検索がヒットしにくい（＝ほぼ全件走査になる）実運用に近いダミーデータを生成する。

    非ヒット行には必ず許可集合外（id >= ALLOWED_SKILL_COUNT）のスキルを混ぜることで、
    LIMIT句による早期終了が起きず、全件走査の実測になるようにする。
    ヒットする行は guaranteed_match_count 件だけ意図的に混ぜ、正しく検出できるかも検証する。
    """
    rng = random.Random(42)

    conn.executemany(
        "INSERT OR IGNORE INTO skills (id, name) VALUES (?, ?)",
        [(i, f"skill_{i}") for i in range(SKILL_COUNT)],
    )

    cur = conn.execute(
        "INSERT INTO import_batches (imported_at, label, row_count) VALUES (?, ?, ?)",
        ("2026-01-01T00:00:00", "ベンチマーク用ダミーデータ", row_count),
    )
    batch_id = cur.lastrowid

    insert_sql = """
        INSERT INTO results (
            batch_id, imported_at, zeny_count, zeny, slot_add, total_cost,
            has_deficiency, print_resistance, skill_mask_lo, skill_mask_hi, skill_sum
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """

    match_positions = set(rng.sample(range(row_count), k=min(guaranteed_match_count, row_count)))

    inserted = 0
    while inserted < row_count:
        batch_len = min(CHUNK_SIZE, row_count - inserted)
        buffer = []
        for offset in range(batch_len):
            row_index = inserted + offset
            if row_index in match_positions:
                # 許可集合内のみで構成し、合計値が2以上になるよう保証する
                skill_ids = rng.sample(range(ALLOWED_SKILL_COUNT), k=rng.choice([1, 2]))
                if len(skill_ids) == 1:
                    skill_sum = rng.choice([2, 3])
                else:
                    skill_sum = sum(rng.choice([1, 2]) for _ in skill_ids)
            else:
                # 許可集合外のスキルを必ず1つ含め、ヒットしないことを保証する
                skill_ids = [rng.randint(ALLOWED_SKILL_COUNT, SKILL_COUNT - 1)]
                if rng.random() < 0.4:
                    skill_ids.append(rng.randint(0, SKILL_COUNT - 1))
                skill_sum = sum(rng.choice([1, 2, 3]) for _ in skill_ids)
            mask_lo, mask_hi = compute_mask(skill_ids)
            buffer.append(
                (
                    batch_id,
                    "2026-01-01T00:00:00",
                    rng.randint(1, 20),
                    rng.randint(50, 500),
                    rng.randint(0, 3),
                    rng.randint(100, 2000),
                    0,
                    0,
                    mask_lo,
                    mask_hi,
                    skill_sum,
                )
            )
        conn.executemany(insert_sql, buffer)
        conn.commit()
        inserted += batch_len
        print(f"  生成中... {inserted}/{row_count}", flush=True)

    return batch_id


def main() -> None:
    parser = argparse.ArgumentParser(description="スキル集合検索のベンチマーク")
    parser.add_argument("row_count", type=int, help="生成するダミーレコード数")
    parser.add_argument("--db-path", default=None, help="DBファイルパス（省略時はカレントに一時作成）")
    parser.add_argument("--keep-db", action="store_true", help="終了後もDBファイルを削除しない")
    args = parser.parse_args()

    db_path = Path(args.db_path) if args.db_path else Path(f"benchmark_{args.row_count}.db")
    if db_path.exists():
        db_path.unlink()

    conn = get_connection(db_path)

    print(f"{args.row_count:,}件のダミーデータを生成中...")
    t0 = time.perf_counter()
    generate_dummy_data(conn, args.row_count)
    gen_elapsed = time.perf_counter() - t0
    print(f"生成完了: {gen_elapsed:.1f}秒")

    allowed_ids = list(range(ALLOWED_SKILL_COUNT))
    params = SearchParams(allowed_skill_ids=allowed_ids, limit=200)

    print("検索を実行中...")
    t0 = time.perf_counter()
    rows = search_results(conn, params)
    search_elapsed = time.perf_counter() - t0
    print(f"検索完了: {search_elapsed:.2f}秒, ヒット件数: {len(rows)}")

    conn.close()
    if not args.keep_db:
        db_path.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
