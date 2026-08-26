CREATE TABLE IF NOT EXISTS skills (
    id   INTEGER PRIMARY KEY,   -- ビットインデックス（0始まり、アプリ側で明示的に採番）
    name TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS import_batches (
    id          INTEGER PRIMARY KEY,
    imported_at TEXT NOT NULL,  -- ISO8601
    label       TEXT,
    row_count   INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS results (
    id                 INTEGER PRIMARY KEY,
    batch_id           INTEGER NOT NULL REFERENCES import_batches(id),
    imported_at        TEXT NOT NULL,
    label              TEXT,   -- 取込バッチのlabelを非正規化（防具での検索用）
    zeny_count         INTEGER,
    zeny               INTEGER,
    slot_add           INTEGER,
    total_cost         INTEGER,
    print_minus        INTEGER,
    print_resistance   INTEGER,
    skill_mask_lo      INTEGER NOT NULL DEFAULT 0,
    skill_mask_hi      INTEGER NOT NULL DEFAULT 0,
    skill_sum          INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS result_skills (
    result_id INTEGER NOT NULL REFERENCES results(id),
    skill_id  INTEGER NOT NULL REFERENCES skills(id),
    value     INTEGER NOT NULL,
    PRIMARY KEY (result_id, skill_id)
);

CREATE INDEX IF NOT EXISTS idx_results_batch_id    ON results(batch_id);
CREATE INDEX IF NOT EXISTS idx_results_imported_at ON results(imported_at);
CREATE INDEX IF NOT EXISTS idx_results_total_cost  ON results(total_cost);
CREATE INDEX IF NOT EXISTS idx_result_skills_skill_id ON result_skills(skill_id);
-- idx_results_label は connection.py の _migrate() 側で作成する
-- （新規DBのCREATE TABLEには既にlabel列が含まれるが、既存DBでは列追加が
--   このスクリプトの後に行われるため、ここで参照すると失敗する）

CREATE TABLE IF NOT EXISTS app_settings (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skill_sets (
    id          INTEGER PRIMARY KEY,
    name        TEXT UNIQUE NOT NULL,
    skill_names TEXT NOT NULL,  -- JSON配列
    created_at  TEXT NOT NULL
);
