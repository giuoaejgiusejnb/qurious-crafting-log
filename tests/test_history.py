import pytest

from app.core.history import delete_batch, fetch_batch_results, list_batches
from app.core.importer import import_block
from app.db.connection import get_connection
from tests.helpers import build_row


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def test_list_batches_returns_newest_first(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]), label="ギルパレ脚")
    summary2 = import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 1)]), label="クシャ胴")

    batches = list_batches(conn)

    assert [b.id for b in batches] == [summary2.batch_id, summary1.batch_id]
    assert batches[0].label == "クシャ胴"
    assert batches[0].row_count == 1


def test_list_batches_returns_empty_list_when_no_batches(conn):
    assert list_batches(conn) == []


def test_fetch_batch_results_filters_by_batch_id(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]))
    text = "\n".join(
        [
            build_row(zeny_count=2, skills=[("攻撃", 1)]),
            build_row(zeny_count=3, skills=[("攻撃", 1)]),
        ]
    )
    summary2 = import_block(conn, text)

    rows = fetch_batch_results(conn, summary2.batch_id)

    assert sorted(r.zeny_count for r in rows) == [2, 3]
    assert summary1.batch_id != summary2.batch_id


def test_fetch_batch_results_supports_pagination(conn):
    text = "\n".join(build_row(zeny_count=i, skills=[("攻撃", 1)]) for i in range(1, 11))
    summary = import_block(conn, text)

    page1 = fetch_batch_results(conn, summary.batch_id, limit=4, offset=0)
    page2 = fetch_batch_results(conn, summary.batch_id, limit=4, offset=4)

    assert [r.zeny_count for r in page1] == [1, 2, 3, 4]
    assert [r.zeny_count for r in page2] == [5, 6, 7, 8]


def test_fetch_batch_results_returns_empty_for_unknown_batch(conn):
    assert fetch_batch_results(conn, 9999) == []


def test_delete_batch_removes_batch_and_its_results(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]))
    summary2 = import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 1)]))

    delete_batch(conn, summary1.batch_id)

    remaining_batch_ids = [b.id for b in list_batches(conn)]
    assert remaining_batch_ids == [summary2.batch_id]
    assert fetch_batch_results(conn, summary1.batch_id) == []
    # 別バッチのresultsは影響を受けない
    assert len(fetch_batch_results(conn, summary2.batch_id)) == 1
    # result_skillsも一緒に消えていること（残っていると孤立行になる）
    orphaned = conn.execute(
        "SELECT COUNT(*) FROM result_skills WHERE result_id NOT IN (SELECT id FROM results)"
    ).fetchone()[0]
    assert orphaned == 0


def test_delete_batch_does_not_renumber_remaining_ids(conn):
    summary1 = import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 1)]))
    summary2 = import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 1)]))
    summary3 = import_block(conn, build_row(zeny_count=3, skills=[("攻撃", 1)]))

    delete_batch(conn, summary2.batch_id)

    remaining_batch_ids = {b.id for b in list_batches(conn)}
    assert remaining_batch_ids == {summary1.batch_id, summary3.batch_id}
