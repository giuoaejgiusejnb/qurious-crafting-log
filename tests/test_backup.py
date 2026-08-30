import sqlite3

import pytest

from app.core.backup import backup_database, restore_database
from app.core.history import list_batches
from app.core.importer import import_block
from app.db.connection import get_connection
from tests.helpers import build_row


@pytest.fixture
def db_path(tmp_path):
    return tmp_path / "test.db"


@pytest.fixture
def conn(db_path):
    connection = get_connection(db_path)
    yield connection
    connection.close()


def test_backup_database_creates_restorable_snapshot(db_path, conn, tmp_path):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))

    dest_path = tmp_path / "backup.db"
    backup_database(db_path, dest_path)

    assert dest_path.exists()
    backup_conn = get_connection(dest_path)
    try:
        assert [b.row_count for b in list_batches(backup_conn)] == [1]
    finally:
        backup_conn.close()


def test_backup_database_reflects_uncommitted_wal_content(db_path, conn, tmp_path):
    # WALモードでは、コミット直後でもチェックポイントされるまでは-walファイルに
    # 内容が残ることがある。VACUUM INTOがそれも正しく反映することを確認する。
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    import_block(conn, build_row(zeny_count=2, skills=[("攻撃", 2)]))

    dest_path = tmp_path / "backup.db"
    backup_database(db_path, dest_path)

    backup_conn = get_connection(dest_path)
    try:
        assert len(list_batches(backup_conn)) == 2
    finally:
        backup_conn.close()


def test_restore_database_replaces_content_with_source(db_path, conn, tmp_path):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))

    source_path = tmp_path / "source.db"
    source_conn = get_connection(source_path)
    try:
        import_block(source_conn, build_row(zeny_count=99, skills=[("見切り", 1)]))
    finally:
        source_conn.close()

    conn.close()  # 復元前に、テスト側が保持している接続を閉じておく
    restore_database(db_path, source_path)

    restored_conn = get_connection(db_path)
    try:
        batches = list_batches(restored_conn)
        assert len(batches) == 1
        assert batches[0].row_count == 1  # source.dbの内容に置き換わっている
    finally:
        restored_conn.close()


def test_restore_database_creates_safety_backup_of_previous_content(db_path, conn, tmp_path):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    conn.close()

    source_path = tmp_path / "source.db"
    get_connection(source_path).close()  # 空のDBを用意

    safety_backup_path = restore_database(db_path, source_path)

    assert safety_backup_path.exists()
    safety_conn = get_connection(safety_backup_path)
    try:
        assert len(list_batches(safety_conn)) == 1  # 復元前の内容が残っている
    finally:
        safety_conn.close()


def test_restore_database_leaves_no_leftover_temp_or_wal_files(db_path, conn, tmp_path):
    import_block(conn, build_row(zeny_count=1, skills=[("攻撃", 2)]))
    conn.close()

    source_path = tmp_path / "source.db"
    get_connection(source_path).close()

    restore_database(db_path, source_path)

    temp_path = db_path.with_name(f"{db_path.name}.restoring")
    assert not temp_path.exists()
    for suffix in ("-wal", "-shm"):
        assert not db_path.with_name(db_path.name + suffix).exists()


def test_restore_database_raises_for_invalid_source(db_path, conn, tmp_path):
    conn.close()
    invalid_source = tmp_path / "not_a_database.db"
    invalid_source.write_text("this is not a sqlite file")

    with pytest.raises(sqlite3.Error):
        restore_database(db_path, invalid_source)
