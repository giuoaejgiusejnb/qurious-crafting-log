import json
import sqlite3


def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        """
        INSERT INTO app_settings (key, value) VALUES (?, ?)
        ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """,
        (key, value),
    )
    conn.commit()


def get_json_setting(conn: sqlite3.Connection, key: str, default: list) -> list:
    raw = get_setting(conn, key)
    if raw is None:
        return default
    return json.loads(raw)


def set_json_setting(conn: sqlite3.Connection, key: str, value: list) -> None:
    set_setting(conn, key, json.dumps(value, ensure_ascii=False))
