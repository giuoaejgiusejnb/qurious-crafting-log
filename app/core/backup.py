"""DBファイルのバックアップ・復元。

SQLiteはWALモードで運用しているため、単純にファイルをコピーするだけでは
書き込み中の内容（-walファイル）が反映されない可能性がある。VACUUM INTOを
使うことで、常に一貫性の取れたスナップショットを1ファイルとして書き出せる。
"""

import os
import shutil
import sqlite3
from datetime import datetime
from pathlib import Path


def backup_database(db_path: Path, dest_path: Path | str) -> None:
    """現在のDBを、一貫性の取れた1ファイルとしてdest_pathに書き出す。

    Raises:
        sqlite3.Error: バックアップに失敗した場合。
    """
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("VACUUM INTO ?", (str(dest_path),))
    finally:
        conn.close()


def restore_database(db_path: Path, source_path: Path | str) -> Path:
    """source_pathの内容でdb_pathを置き換える。

    復元前のdb_pathの内容は自動でタイムスタンプ付きのファイル名でバックアップし、
    そのパスを返す。書き込みは一時ファイルに対して行ってから最後にos.replace()で
    入れ替えるため、途中で失敗してもdb_pathの内容は壊れない
    （db_pathがまだ存在する場合は、そのままの状態で残る）。

    Raises:
        sqlite3.Error: source_pathの読み込みに失敗した場合。
        OSError: ファイル操作に失敗した場合。
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    safety_backup_path = db_path.with_name(
        f"{db_path.stem}_before_restore_{timestamp}{db_path.suffix}"
    )
    temp_path = db_path.with_name(f"{db_path.name}.restoring")

    if db_path.exists():
        shutil.copy2(db_path, safety_backup_path)

    if temp_path.exists():
        temp_path.unlink()

    source_conn = sqlite3.connect(source_path)
    try:
        source_conn.execute("VACUUM INTO ?", (str(temp_path),))
    finally:
        source_conn.close()

    os.replace(temp_path, db_path)
    # 置き換え後、古いDBのWAL/SHMが残っていると新しい本体とズレるため削除する
    for suffix in ("-wal", "-shm"):
        stale = db_path.with_name(db_path.name + suffix)
        if stale.exists():
            stale.unlink()

    return safety_backup_path
