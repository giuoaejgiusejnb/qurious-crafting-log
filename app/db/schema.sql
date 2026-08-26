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
