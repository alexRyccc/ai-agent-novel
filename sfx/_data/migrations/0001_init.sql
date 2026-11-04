-- SkillForge migration 0001 —— 初始最小 Schema（Walking Skeleton）
--
-- 设计纪律（ARCH §7.3.2 / §10.5）：
--   D-2 禁止 strftime / julianday / ifnull 等方言函数（本文件未使用）
--   D-3 禁止 AUTOINCREMENT；主键一律 uuidv7 字符串（时间有序）
--   D-5 时间一律 RFC3339 UTC 字符串，由应用层生成，不用 datetime('now')
--
-- WS 范围说明：这里只建 WS-1/WS-2 需要的表（skills / sessions / call_events）。
-- 其余表（skill_versions / tags / feedbacks / skill_scores / convention_files …）
-- 属于后续里程碑，会在 0002+ 中增量添加，用户无需手工执行 migrate。

CREATE TABLE IF NOT EXISTS schema_migrations (
    version    INTEGER PRIMARY KEY,
    name       TEXT NOT NULL,
    applied_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS skills (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    slug             TEXT NOT NULL,
    summary          TEXT NOT NULL DEFAULT '',
    description      TEXT NOT NULL DEFAULT '',
    source_root      TEXT NOT NULL,
    dir_path         TEXT NOT NULL,
    entry_path       TEXT NOT NULL,
    author           TEXT NOT NULL DEFAULT '',
    version          INTEGER NOT NULL DEFAULT 1,
    status           TEXT NOT NULL DEFAULT 'active',
    content_hash     TEXT NOT NULL DEFAULT '',
    body_bytes       INTEGER NOT NULL DEFAULT 0,
    triggers_json    TEXT NOT NULL DEFAULT '[]',
    tags_json        TEXT NOT NULL DEFAULT '[]',
    summary_fallback INTEGER NOT NULL DEFAULT 0,
    created_at       TEXT NOT NULL,
    updated_at       TEXT NOT NULL,
    last_scanned_at  TEXT NOT NULL
);

-- 重复扫描不产生重复记录（FR-01）
CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_slug ON skills (slug);
CREATE UNIQUE INDEX IF NOT EXISTS ux_skills_src_dir ON skills (source_root, dir_path);
CREATE INDEX IF NOT EXISTS ix_skills_status ON skills (status, updated_at);

-- 隐私说明：sessions 不存任务正文，只存 task_hash(FNV-1a) 与 task_len（ARCH §10.3 / NFR-04 ③）
CREATE TABLE IF NOT EXISTS sessions (
    id            TEXT PRIMARY KEY,
    task_hash     TEXT NOT NULL,
    task_len      INTEGER NOT NULL DEFAULT 0,
    channel       TEXT NOT NULL DEFAULT 'cli',
    project_root  TEXT NOT NULL DEFAULT '',
    match_count   INTEGER NOT NULL DEFAULT 0,
    top_score     REAL NOT NULL DEFAULT 0,
    top_skill_id  TEXT NOT NULL DEFAULT '',
    created_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS call_events (
    id             TEXT PRIMARY KEY,
    session_id     TEXT NOT NULL,
    skill_id       TEXT NOT NULL,
    type           TEXT NOT NULL,
    rank           INTEGER NOT NULL DEFAULT 0,
    score          REAL NOT NULL DEFAULT 0,
    elapsed_ms     INTEGER NOT NULL DEFAULT 0,
    engine_version TEXT NOT NULL DEFAULT '',
    channel        TEXT NOT NULL DEFAULT 'cli',
    payload_json   TEXT NOT NULL DEFAULT '{}',
    created_at     TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_events_skill ON call_events (skill_id, created_at);
CREATE INDEX IF NOT EXISTS ix_events_created ON call_events (created_at);
CREATE INDEX IF NOT EXISTS ix_events_session ON call_events (session_id);
