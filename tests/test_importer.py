import pytest

from app.core.importer import import_block
from app.core.skill_mask import compute_mask
from app.db.connection import get_connection


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


SAMPLE_TEXT = "\n".join(
    [
        "5,120,1,500,0,0,攻撃+1,見切り+1",
        "5,120,1,500,0,0,攻撃+2",
        "invalid,line",
        "5,120,1,500,0,0",
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
    import_block(conn, "5,120,1,500,0,0,攻撃+1")
    import_block(conn, "5,120,1,500,0,0,攻撃+1,見切り+1")

    skill_ids = {
        name: skill_id
        for skill_id, name in conn.execute("SELECT id, name FROM skills").fetchall()
    }
    assert skill_ids == {"攻撃": 0, "見切り": 1}


def test_import_block_reports_progress(conn):
    calls = []
    import_block(conn, SAMPLE_TEXT, progress_callback=lambda done, total: calls.append((done, total)))
    assert calls[-1] == (3, 3)
