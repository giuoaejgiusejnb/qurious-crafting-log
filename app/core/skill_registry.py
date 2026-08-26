import sqlite3


class SkillRegistry:
    """スキル名とビットインデックス（skills.id）の対応を管理する。

    ビットインデックスは0始まりで単調増加のみ（欠番を出さない前提）。
    スキルは削除しない運用のため、既存件数をそのまま次の空きインデックスとして使える。
    """

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn
        self._name_to_id: dict[str, int] = {}
        self._load()

    def _load(self) -> None:
        rows = self._conn.execute("SELECT id, name FROM skills").fetchall()
        self._name_to_id = {name: skill_id for skill_id, name in rows}

    def get_or_create_id(self, name: str) -> int:
        existing = self._name_to_id.get(name)
        if existing is not None:
            return existing

        new_id = len(self._name_to_id)
        self._conn.execute("INSERT INTO skills (id, name) VALUES (?, ?)", (new_id, name))
        self._name_to_id[name] = new_id
        return new_id

    def get_ids(self, names: list[str]) -> list[int]:
        """既存スキル名のみをIDに変換する（検索条件の組み立て用）。未登録の名前は無視する。"""
        return [self._name_to_id[n] for n in names if n in self._name_to_id]
