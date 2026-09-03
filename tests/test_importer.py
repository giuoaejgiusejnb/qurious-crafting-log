import pytest

from app.core.importer import import_block
from app.core.skill_mask import compute_mask
from app.db.connection import get_connection
from tests.helpers import build_row


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


SAMPLE_TEXT = "\n".join(
    [
        build_row(zeny_count=5, skills=[("攻撃", 1), ("見切り", 1)]),
        build_row(zeny_count=6, skills=[("攻撃", 2)]),
        "invalid,line",
        build_row(zeny_count=7),
    ]
)


def test_import_block_creates_batch(conn):
    summary = import_block(conn, SAMPLE_TEXT, label="テスト取込")

    assert summary.imported_count == 3
    assert summary.error_count == 1
    assert summary.errors[0][1]  # メッセージが入っている

    batch_row = conn.execute(
        "SELECT label, row_count FROM import_batches WHERE id = ?", (summary.batch_id,)
    ).fetchone()
    assert batch_row == ("テスト取込", 3)


def test_import_block_copies_label_onto_each_result(conn):
    summary = import_block(conn, SAMPLE_TEXT, label="ギルパレ脚")

    labels = conn.execute(
        "SELECT label FROM results WHERE batch_id = ?", (summary.batch_id,)
    ).fetchall()
    assert all(row == ("ギルパレ脚",) for row in labels)
    assert len(labels) == 3


def test_import_block_computes_correct_mask_and_sum(conn):
    summary = import_block(conn, SAMPLE_TEXT)

    rows = conn.execute(
        "SELECT skill_mask_lo, skill_mask_hi, skill_sum FROM results WHERE batch_id = ? ORDER BY id",
        (summary.batch_id,),
    ).fetchall()

    # 1行目: 攻撃(id=0)+見切り(id=1)
    expected_lo, expected_hi = compute_mask([0, 1])
    assert rows[0] == (expected_lo, expected_hi, 2)

    # 2行目: 攻撃(id=0)のみ、値2
    expected_lo2, expected_hi2 = compute_mask([0])
    assert rows[1] == (expected_lo2, expected_hi2, 2)

    # 3行目（元の4行目）: スキルなし
    assert rows[2] == (0, 0, 0)


def test_import_block_populates_result_skills(conn):
    summary = import_block(conn, SAMPLE_TEXT)

    skill_rows = conn.execute(
        """
        SELECT s.name, rs.value
        FROM result_skills rs
        JOIN skills s ON s.id = rs.skill_id
        JOIN results r ON r.id = rs.result_id
        WHERE r.batch_id = ?
        ORDER BY r.id, s.name
        """,
        (summary.batch_id,),
    ).fetchall()

    assert skill_rows == [("攻撃", 1), ("見切り", 1), ("攻撃", 2)]


def test_import_block_reuses_skill_ids_across_calls(conn):
    import_block(conn, build_row(skills=[("攻撃", 1)]))
    import_block(conn, build_row(skills=[("攻撃", 1), ("見切り", 1)]))

    skill_ids = {
        name: skill_id
        for skill_id, name in conn.execute("SELECT id, name FROM skills").fetchall()
    }
    assert skill_ids == {"攻撃": 0, "見切り": 1}


def test_import_block_reports_progress(conn):
    calls = []
    import_block(conn, SAMPLE_TEXT, progress_callback=lambda done, total: calls.append((done, total)))
    assert calls[-1] == (3, 3)


def test_import_block_stores_deficiency_and_resistance(conn):
    line = build_row(deficiency="有", resistance=-5, skills=[("火事場力", -1)])
    summary = import_block(conn, line)

    row = conn.execute(
        "SELECT has_deficiency, print_resistance FROM results WHERE batch_id = ?",
        (summary.batch_id,),
    ).fetchone()
    assert row == (1, -5)


# --- 重複行（幽霊行）の除去 ---


def _zeny_counts(conn, batch_id):
    return [
        r[0]
        for r in conn.execute(
            "SELECT zeny_count FROM results WHERE batch_id = ? ORDER BY id", (batch_id,)
        )
    ]


def test_dedupe_keeps_row_with_skills_over_empty_row(conn):
    text = "\n".join(
        [
            build_row(zeny_count=10, slot_add=1, total_cost=6, skills=[("攻撃", 1)]),
            build_row(zeny_count=10, slot_add=-3, total_cost=-18),
            build_row(zeny_count=11, skills=[("見切り", 1)]),
        ]
    )
    summary = import_block(conn, text)

    assert summary.imported_count == 2
    assert summary.dropped_duplicate_count == 1
    rows = conn.execute(
        "SELECT zeny_count, slot_add, total_cost FROM results WHERE batch_id = ? ORDER BY id",
        (summary.batch_id,),
    ).fetchall()
    assert rows == [(10, 1, 6), (11, 0, 0)]


def test_dedupe_drops_phantom_signature_when_both_rows_have_no_skills(conn):
    text = "\n".join(
        [
            build_row(zeny_count=20, slot_add=0, total_cost=3),
            build_row(zeny_count=20, slot_add=-3, total_cost=-18),
            build_row(zeny_count=21),
        ]
    )
    summary = import_block(conn, text)

    assert summary.imported_count == 2
    assert summary.dropped_duplicate_count == 1
    rows = conn.execute(
        "SELECT slot_add, total_cost FROM results WHERE batch_id = ? ORDER BY id",
        (summary.batch_id,),
    ).fetchall()
    assert rows == [(0, 3), (0, 0)]  # -3/-18 の行が消え、もう片方が残る


def test_dedupe_keeps_first_when_no_row_stands_out(conn):
    text = "\n".join(
        [
            build_row(zeny_count=30, slot_add=-3, total_cost=-18, resistance=1),
            build_row(zeny_count=30, slot_add=-3, total_cost=-18, resistance=2),
            build_row(zeny_count=31),
        ]
    )
    summary = import_block(conn, text)

    assert summary.imported_count == 2
    rows = conn.execute(
        "SELECT print_resistance FROM results WHERE batch_id = ? ORDER BY id",
        (summary.batch_id,),
    ).fetchall()
    assert rows == [(1,), (0,)]  # 先頭（resistance=1）が残る


def test_dedupe_does_not_touch_non_consecutive_same_count(conn):
    text = "\n".join(
        [
            build_row(zeny_count=40, skills=[("攻撃", 1)]),
            build_row(zeny_count=41, skills=[("攻撃", 1)]),
            build_row(zeny_count=40, skills=[("攻撃", 1)]),
        ]
    )
    summary = import_block(conn, text)

    assert summary.imported_count == 3
    assert summary.dropped_duplicate_count == 0


# --- 飛ばされている練成（欠番）の検出 ---


def test_skipped_results_detected_and_persisted(conn):
    text = "\n".join(
        [
            build_row(zeny_count=100, zeny=9600),
            build_row(zeny_count=101, zeny=9596),
            build_row(zeny_count=104, zeny=9584),  # 102, 103 が欠番（1練成4ゼニー減）
        ]
    )
    summary = import_block(conn, text)

    assert summary.skipped_results == [(102, 9592), (103, 9588)]
    assert summary.error_count == 2  # 読込失敗0 + 欠番2

    rows = conn.execute(
        "SELECT zeny_count, detail FROM import_issues "
        "WHERE batch_id = ? AND kind = 'skipped' ORDER BY zeny_count",
        (summary.batch_id,),
    ).fetchall()
    assert rows == [(102, "9592"), (103, "9588")]


def test_skipped_result_zeny_is_none_when_step_not_divisible(conn):
    text = "\n".join(
        [
            build_row(zeny_count=10, zeny=1000),
            build_row(zeny_count=13, zeny=993),  # 差7は3で割り切れない
        ]
    )
    summary = import_block(conn, text)

    assert summary.skipped_results == [(11, None), (12, None)]


def test_phantom_removal_reveals_skipped_result(conn):
    """幽霊行を挟んで実行が1つ抜けるケース（回数774→幽霊774→回数776 相当）。"""
    text = "\n".join(
        [
            build_row(zeny_count=774, zeny=96903, skills=[("攻撃", 1)]),
            build_row(zeny_count=774, zeny=96903, slot_add=-3, total_cost=-18),
            build_row(zeny_count=776, zeny=96895, skills=[("攻撃", 1)]),
        ]
    )
    summary = import_block(conn, text)

    assert summary.imported_count == 2
    assert summary.dropped_duplicate_count == 1
    assert summary.skipped_results == [(775, 96899)]


def test_large_gap_is_ignored(conn):
    text = "\n".join(
        [
            build_row(zeny_count=1),
            build_row(zeny_count=9999),  # OCR誤読相当の外れ値。欠番扱いにしない
        ]
    )
    summary = import_block(conn, text)

    assert summary.skipped_results == []


# --- パースエラーの永続化 ---


def test_unparsable_line_persisted_with_zeny_count(conn):
    broken = "1248,95007,1,6,無,-2,火属性攻撃強化,,,,,,,,,,,,0"  # スキル値が空
    text = "\n".join([build_row(zeny_count=1), broken, build_row(zeny_count=2)])
    summary = import_block(conn, text)

    assert summary.error_count == 1
    row = conn.execute(
        "SELECT kind, zeny_count FROM import_issues WHERE batch_id = ? AND kind = 'unparsable'",
        (summary.batch_id,),
    ).fetchone()
    assert row == ("unparsable", 1248)
