import datetime as dt
import sqlite3
from dataclasses import dataclass, field
from typing import Callable

from app.core.models import ParsedResult
from app.core.parser import parse_result_log_block
from app.core.skill_mask import compute_mask
from app.core.skill_registry import SkillRegistry

ProgressCallback = Callable[[int, int], None]

# 回数の欠番を「飛ばされている行」として記録する際、この幅を超える欠落は
# マクロの長時間停止やゼニーOCRの誤読による外れ値とみなし、記録しない。
# 幽霊行の除去で生じる欠番は高々1〜数回分のため、これで十分カバーできる。
_MAX_GAP_TO_REPORT = 50


@dataclass
class ImportSummary:
    batch_id: int
    imported_count: int
    error_count: int
    errors: list[tuple[int, str]] = field(default_factory=list)
    # 除去後の回数列で欠番になっている練成 [(練成回数, 推定ゼニー or None), ...]
    skipped_results: list[tuple[int, int | None]] = field(default_factory=list)
    # 重複（幽霊行）として除去した行数。表示用途のみでDBには保存しない
    dropped_duplicate_count: int = 0


def _row_keep_score(result: ParsedResult) -> tuple[bool, bool]:
    """同一回数グループ内で「残す行」を選ぶための優先度スコア。

    大きいほど残す優先度が高い。
    1. スキルがある行を優先して残す
    2. どれもスキル0個なら、slot_add==-3 かつ total_cost==-18 の行（空振り読み取りの
       典型シグネチャ）を優先して除去する ＝ それ以外の行を残す
    同点は呼び出し側で出現順の最先を残す。
    """
    has_skills = len(result.skills) > 0
    is_phantom_signature = result.slot_add == -3 and result.total_cost == -18
    return (has_skills, not is_phantom_signature)


def _dedupe_consecutive_duplicates(
    results: list[ParsedResult],
) -> tuple[list[ParsedResult], int]:
    """回数（zeny_count）が同じ行が連続している箇所を1行に畳む。

    ゼニーは1練成ごとに必ず減るため、回数が前行と同値の行は実際には練成が
    行われていない空振り読み取り（幽霊行）。グループごとに _row_keep_score が
    最大の行を1つだけ残す（同点は最先）。

    戻り値は (除去後のリスト, 除去した行数)。
    """
    kept: list[ParsedResult] = []
    dropped = 0

    i = 0
    n = len(results)
    while i < n:
        j = i
        while j + 1 < n and results[j + 1].zeny_count == results[i].zeny_count:
            j += 1
        group = results[i : j + 1]
        if len(group) == 1:
            kept.append(group[0])
        else:
            best = 0
            for k in range(1, len(group)):
                if _row_keep_score(group[k]) > _row_keep_score(group[best]):
                    best = k
            kept.append(group[best])
            dropped += len(group) - 1
        i = j + 1

    return kept, dropped


def _find_skipped_results(results: list[ParsedResult]) -> list[tuple[int, int | None]]:
    """除去後の回数列で内側に欠けている練成を [(練成回数, 推定ゼニー), ...] で返す。

    ゼニーの1練成あたり減少量はバッチ内で一定なので、欠番を挟む前後の採用行
    (c1, z1) (c2, z2) から step = (z1 - z2) / (c2 - c1) を求め、
    zeny(k) = z1 - step * (k - c1) で補間する。割り切れない・ゼニーが非単調など
    信頼できない場合はゼニーを None にする。
    _MAX_GAP_TO_REPORT を超える大きな欠落は外れ値とみなして無視する。
    """
    zeny_by_count: dict[int, int] = {}
    for r in results:
        zeny_by_count.setdefault(r.zeny_count, r.zeny)
    counts = sorted(zeny_by_count)

    skipped: list[tuple[int, int | None]] = []
    for c1, c2 in zip(counts, counts[1:]):
        span = c2 - c1
        if not 1 < span <= _MAX_GAP_TO_REPORT + 1:
            continue
        z1, z2 = zeny_by_count[c1], zeny_by_count[c2]
        diff = z1 - z2
        step = diff // span if diff > 0 and diff % span == 0 else None
        for k in range(c1 + 1, c2):
            skipped.append((k, z1 - step * (k - c1) if step is not None else None))
    return skipped


def _extract_zeny_count_from_message(message: str) -> int | None:
    """パースエラーメッセージから、対象行の先頭にある回数だけ取り出せれば返す。

    パーサーのメッセージは末尾に元の行を「行全体: ...」または「: ...」の形で含む。
    """
    marker = "行全体: "
    idx = message.find(marker)
    tail = message[idx + len(marker) :] if idx != -1 else message.rsplit(": ", 1)[-1]
    head = tail.split(",", 1)[0].strip().rstrip("）)")
    try:
        return int(head)
    except ValueError:
        return None


def import_block(
    conn: sqlite3.Connection,
    text: str,
    label: str | None = None,
    progress_callback: ProgressCallback | None = None,
) -> ImportSummary:
    """result_logのテキストブロックをパースし、1つの取込バッチとしてDBに保存する。

    - パースできなかった行はスキップし、error一覧として返す。
    - 回数が連続で重複する幽霊行は1行に畳んでから保存する。
    - 畳んだ結果の回数列に欠番があれば「飛ばされている行」として記録する。
    パースエラーと欠番は import_issues テーブルに保存し、履歴タブの「エラー」欄で参照する。
    """
    parsed, errors = parse_result_log_block(text)
    results, dropped_duplicate_count = _dedupe_consecutive_duplicates(parsed)

    error_zeny_counts = {
        zc for _, message in errors if (zc := _extract_zeny_count_from_message(message)) is not None
    }
    # パースできなかった行の回数は「読み込みできなかった行」側で報告するため、
    # その欠番は「飛ばされている練成」からは除く。
    skipped_results = [
        (count, zeny)
        for count, zeny in _find_skipped_results(results)
        if count not in error_zeny_counts
    ]

    imported_at = dt.datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO import_batches (imported_at, label, row_count, errors_analyzed) "
        "VALUES (?, ?, ?, 1)",
        (imported_at, label, len(results)),
    )
    batch_id = cur.lastrowid

    if errors:
        conn.executemany(
            """
            INSERT INTO import_issues (batch_id, kind, line_number, zeny_count, detail)
            VALUES (?, 'unparsable', ?, ?, ?)
            """,
            [
                (batch_id, line_number, _extract_zeny_count_from_message(message), message)
                for line_number, message in errors
            ],
        )
    if skipped_results:
        conn.executemany(
            """
            INSERT INTO import_issues (batch_id, kind, line_number, zeny_count, detail)
            VALUES (?, 'skipped', NULL, ?, ?)
            """,
            [
                (batch_id, count, None if zeny is None else str(zeny))
                for count, zeny in skipped_results
            ],
        )

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
                has_deficiency, print_resistance, skill_mask_lo, skill_mask_hi, skill_sum
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
                result.has_deficiency,
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
        error_count=len(errors) + len(skipped_results),
        errors=errors,
        skipped_results=skipped_results,
        dropped_duplicate_count=dropped_duplicate_count,
    )
