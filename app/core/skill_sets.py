import datetime as dt
import json
import sqlite3


def save_skill_set(conn: sqlite3.Connection, name: str, skill_names: list[str]) -> None:
    """名前付きスキル集合を保存する。同名が既にあれば内容を上書きする。"""
    created_at = dt.datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO skill_sets (name, skill_names, created_at) VALUES (?, ?, ?)
        ON CONFLICT(name) DO UPDATE SET skill_names = excluded.skill_names, created_at = excluded.created_at
        """,
        (name, json.dumps(skill_names, ensure_ascii=False), created_at),
    )
    conn.commit()


def list_skill_set_names(conn: sqlite3.Connection) -> list[str]:
    rows = conn.execute("SELECT name FROM skill_sets ORDER BY name").fetchall()
    return [r[0] for r in rows]


def get_skill_set(conn: sqlite3.Connection, name: str) -> list[str] | None:
    row = conn.execute("SELECT skill_names FROM skill_sets WHERE name = ?", (name,)).fetchone()
    if row is None:
        return None
    return json.loads(row[0])


def delete_skill_set(conn: sqlite3.Connection, name: str) -> None:
    conn.execute("DELETE FROM skill_sets WHERE name = ?", (name,))
    conn.commit()
