"""前向迁移器：**用户永远不需要手动执行 migrate**（ARCH §4.3 / WS-1 W1-5）。

性能设计（这条很关键）
----------------------
迁移 SQL 存在包内 ``_data/migrations/`` 里，只能通过 ``importlib.resources`` 读取，
而该模块实测增量 **+205ms**。如果每次 ``sfx match`` 都去读一遍迁移文件，
``match`` 的 p95 必然爆掉 300ms 红线（NFR-05）。

因此这里的策略是：**版本号用 Python 常量写死**（零 IO、零导入），
只有当 ``schema_migrations`` 里的版本确实落后时才去加载 SQL 文件。
于是：
  - 首次运行（建库）：付一次 205ms，可接受；
  - 之后每一次：只跑一条 ``SELECT MAX(version)``，代价 ≈ 0。
"""

from __future__ import annotations

import sqlite3

from sfx._errors import E_STORE, SfxError

#: 本版本 sfx 认识的最新 migration 版本号（必须与 ``_data/migrations/`` 里最大的编号一致）
LATEST_VERSION = 1

#: 版本号 → 包内资源相对路径
MIGRATIONS: dict[int, str] = {
    1: "migrations/0001_init.sql",
}


def current_version(conn: sqlite3.Connection) -> int:
    """返回已应用的最大 migration 版本号；库为空时返回 0。"""
    try:
        row = conn.execute(
            "SELECT version FROM schema_migrations ORDER BY version DESC LIMIT 1"
        ).fetchone()
    except sqlite3.Error:
        return 0
    if row is None:
        return 0
    try:
        return int(row[0])
    except (TypeError, ValueError):
        return 0


def applied_versions(conn: sqlite3.Connection) -> list[int]:
    """返回已应用的全部版本号（升序），供 ``sfx doctor`` 展示。"""
    try:
        rows = conn.execute("SELECT version FROM schema_migrations ORDER BY version").fetchall()
    except sqlite3.Error:
        return []
    return [int(row[0]) for row in rows if row[0] is not None]


def _ensure_meta_table(conn: sqlite3.Connection) -> None:
    """创建 ``schema_migrations`` 元表（它必须先于任何业务表存在）。"""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " version INTEGER PRIMARY KEY,"
        " name TEXT NOT NULL,"
        " applied_at TEXT NOT NULL)"
    )


def migrate(conn: sqlite3.Connection, now_text: str) -> list[int]:
    """把数据库迁移到 ``LATEST_VERSION``，返回本次实际应用的版本号列表。

    Args:
        conn: 已打开的连接。
        now_text: RFC3339 UTC 时间戳（由应用层生成，遵守 D-5）。

    Raises:
        SfxError: ``E_STORE`` —— 迁移脚本缺失或执行失败。
    """
    _ensure_meta_table(conn)
    applied = current_version(conn)
    if applied >= LATEST_VERSION:
        return []

    # 只有确实落后时才延迟导入资源层（+205ms），这是守住 match p95 的关键
    from sfx import _res

    done: list[int] = []
    for version in sorted(MIGRATIONS):
        if version <= applied:
            continue
        resource = MIGRATIONS[version]
        try:
            sql = _res.read_text(resource)
        except OSError as exc:
            raise SfxError(
                E_STORE,
                f"迁移脚本缺失：{resource}",
                {"version": version, "resource": resource},
                "该 sfx.pyz 可能损坏，请重新获取完整产物",
            ) from exc
        try:
            conn.executescript(sql)
        except sqlite3.Error as exc:
            conn.rollback()
            raise SfxError(
                E_STORE,
                f"执行 migration {version} 失败：{exc}",
                {"version": version, "resource": resource},
                "检查磁盘空间；数据库未改动，可重试",
            ) from exc
        conn.execute(
            "INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)",
            (version, resource, now_text),
        )
        conn.commit()
        done.append(version)
    return done
