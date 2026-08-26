import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from app.core.parser import parse_result_log_block
from app.core.skill_mask import compute_mask
from app.core.skill_registry import SkillRegistry

ProgressCallback = Callable[[int, int], None]


@dataclass
class ImportSummary:
    batch_id: int
    imported_count: int
    error_count: int
    errors: list[tuple[int, str]] = field(default_factory=list)


def import_block(
    conn: sqlite3.Connection,
    text: str,
    label: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ImportSummary:
    """result_logのテキストブロックをパースし、1つの取込バッチとしてDBに保存する。

    不正な行はスキップし、成功件数とは別にエラー一覧として返す。
    """
    results, errors = parse_result_log_block(text)

    imported_at = dt.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO import_batches (imported_at, label, row_count) VALUES (?, ?, ?)",
        (imported_at, label, len(results)),
    )
    batch_id = cur.lastrowid

    registry = SkillRegistry(conn)
    total = len(results)

    for i, result in enumerate(results, start=1):
        skill_ids = [registry.get_or_create_id(s.name) for s in result.skills]
        mask_lo, mask_hi = compute_mask(skill_ids)
        skill_sum = sum(s.value for s in result.skills)

        cur = conn.execute(
            """
            INSERT INTO results (
                batch_id, imported_at, label, zeny_count, zeny, slot_add, total_cost,
                print_minus, print_resistance, skill_mask_lo, skill_mask_hi, skill_sum
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                batch_id,
                imported_at,
                label,
                result.zeny_count,
                result.zeny,
                result.slot_add,
                result.total_cost,
                result.print_minus,
                result.print_resistance,
                mask_lo,
                mask_hi,
                skill_sum,
            ),
        )
        result_id = cur.lastrowid

        if result.skills:
            conn.executemany(
                "INSERT INTO result_skills (result_id, skill_id, value) VALUES (?, ?, ?)",
                [(result_id, sid, s.value) for sid, s in zip(skill_ids, result.skills)],
            )

        if progress_callback and (i % 500 == 0 or i == total):
            progress_callback(i, total)

    conn.commit()

    return ImportSummary(
        batch_id=batch_id,
        imported_count=total,
        error_count=len(errors),
        errors=errors,
    )
