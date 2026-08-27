import sqlite3
from pathlib import Path

_SCHEMA_PATH = Path(__file__).parent / "schema.sql"


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTSでは反映されない、既存DBへの列追加を行う。

    schema.sqlに新しい列を足しただけでは、既にresultsテーブルを持つ既存のDB
    ファイルには反映されない（IF NOT EXISTSはテーブル単位のため）。ここで
    不足している列を検出しALTER TABLEで補う。
    """
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(results)").fetchall()}
    if "label" not in existing_columns:
        conn.execute("ALTER TABLE results ADD COLUMN label TEXT")
        existing_columns.add("label")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_results_label ON results(label)")

    # print_minus は「スキル欠け」概念に合わせて has_deficiency へ改名した
    if "has_deficiency" not in existing_columns:
        if "print_minus" in existing_columns:
            conn.execute("ALTER TABLE results RENAME COLUMN print_minus TO has_deficiency")
        else:
            conn.execute("ALTER TABLE results ADD COLUMN has_deficiency INTEGER")

    conn.commit()


def get_connection(db_path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.executescript(_SCHEMA_PATH.read_text(encoding="utf-8"))
    conn.commit()
    _migrate(conn)
    return conn
