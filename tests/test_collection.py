import pytest

from app.core.collection import (
    MAX_COLLECTED,
    CollectionLimitError,
    count_collected,
    fetch_collected_in_batch,
    set_collected,
)
from app.core.importer import import_block
from app.db.connection import get_connection
from tests.helpers import build_row


@pytest.fixture
def conn(tmp_path):
    connection = get_connection(tmp_path / "test.db")
    yield connection
    connection.close()


def _import_batch(conn, zeny_counts: list[int]) -> tuple[int, list[int]]:
    """指定した練成回数の行を1バッチとして取り込み、(batch_id, [result_id, ...])を返す。"""
    text = "\n".join(build_row(zeny_count=i) for i in zeny_counts)
    import_block(conn, text)
    batch_id = conn.execute("SELECT MAX(batch_id) FROM results").fetchone()[0]
    ids = [
        r[0]
        for r in conn.execute(
            "SELECT id FROM results WHERE batch_id = ? ORDER BY id", (batch_id,)
        ).fetchall()
    ]
    return batch_id, ids


def test_count_collected_starts_at_zero(conn):
    batch_id, _ids = _import_batch(conn, [1, 2, 3])
    assert count_collected(conn, batch_id) == 0


def test_set_collected_true_then_false(conn):
    batch_id, ids = _import_batch(conn, [1])
    set_collected(conn, ids[0], batch_id, True)
    assert count_collected(conn, batch_id) == 1

    set_collected(conn, ids[0], batch_id, False)
    assert count_collected(conn, batch_id) == 0


def test_set_collected_true_is_idempotent(conn):
    batch_id, ids = _import_batch(conn, [1])
    set_collected(conn, ids[0], batch_id, True)
    set_collected(conn, ids[0], batch_id, True)
    assert count_collected(conn, batch_id) == 1


def test_set_collected_raises_when_limit_reached(conn, monkeypatch):
    monkeypatch.setattr("app.core.collection.MAX_COLLECTED", 2)
    batch_id, ids = _import_batch(conn, [1, 2, 3])

    set_collected(conn, ids[0], batch_id, True)
    set_collected(conn, ids[1], batch_id, True)

    with pytest.raises(CollectionLimitError):
        set_collected(conn, ids[2], batch_id, True)

    assert count_collected(conn, batch_id) == 2


def test_set_collected_does_not_raise_when_rechecking_at_limit(conn, monkeypatch):
    monkeypatch.setattr("app.core.collection.MAX_COLLECTED", 1)
    batch_id, ids = _import_batch(conn, [1])

    set_collected(conn, ids[0], batch_id, True)
    set_collected(conn, ids[0], batch_id, True)  # 既にチェック済みなので上限に達していても例外にならない
    assert count_collected(conn, batch_id) == 1


def test_collection_limit_is_independent_per_batch(conn, monkeypatch):
    # 上限はバッチごとに独立しており、他バッチの回収件数とは共有しない
    monkeypatch.setattr("app.core.collection.MAX_COLLECTED", 1)
    batch1_id, batch1_ids = _import_batch(conn, [1])
    batch2_id, batch2_ids = _import_batch(conn, [1])

    set_collected(conn, batch1_ids[0], batch1_id, True)
    assert count_collected(conn, batch1_id) == 1

    # batch1は既に上限（1件）だが、batch2は別枠なのでチェックできる
    set_collected(conn, batch2_ids[0], batch2_id, True)
    assert count_collected(conn, batch2_id) == 1


def test_fetch_collected_in_batch_filters_by_batch_and_collected(conn):
    batch1_id, batch1_ids = _import_batch(conn, [1, 2])
    batch2_id, _batch2_ids = _import_batch(conn, [10, 20])

    set_collected(conn, batch1_ids[0], batch1_id, True)  # batch1の1件だけチェック
    set_collected(conn, batch1_ids[1], batch1_id, False)

    rows = fetch_collected_in_batch(conn, batch1_id)
    assert [r.id for r in rows] == [batch1_ids[0]]

    rows2 = fetch_collected_in_batch(conn, batch2_id)
    assert rows2 == []


def test_fetch_collected_in_batch_orders_by_zeny_count(conn):
    batch_id, ids = _import_batch(conn, [30, 10, 20])
    for result_id in ids:
        set_collected(conn, result_id, batch_id, True)

    rows = fetch_collected_in_batch(conn, batch_id)

    assert [r.zeny_count for r in rows] == [10, 20, 30]


def test_max_collected_constant_is_200():
    assert MAX_COLLECTED == 200
