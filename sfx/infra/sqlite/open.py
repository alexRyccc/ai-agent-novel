"""数据库打开与 PRAGMA 设置（ARCH §3.2）。

三条 PRAGMA 的作用
------------------
- ``journal_mode=WAL``：读不阻塞写，``sfx match`` 与 ``sfx scan`` 可并发（§2.3.5
  的"读多写少"场景）；
- ``busy_timeout=5000``：拿到锁前最多等 5s，配合短事务吸收写并发；
- ``timeout=5.0``（connect 参数）：Python 侧的连接级超时，双保险。

全部已由架构师实测可用（SQLite 3.53.1）。
"""

from __future__ import annotations

import sqlite3

from sfx.infra import pathx
from sfx._errors import E_STORE, SfxError


def open_db(db_path: str) -> sqlite3.Connection:
    """打开（必要时创建）SQLite 数据库并完成 PRAGMA 设置。

    Args:
        db_path: 数据库文件绝对路径。

    Returns:
        已设置好 PRAGMA 的连接。

    Raises:
        SfxError: ``E_STORE`` —— 目录不可创建、文件不可打开或不是合法 SQLite 库。
    """
    pathx.ensure_parent(db_path)
    try:
        conn = sqlite3.connect(db_path, timeout=5.0)
    except sqlite3.Error as exc:
        raise SfxError(
            E_STORE,
            f"无法打开数据库：{db_path}",
            {"path": db_path, "reason": str(exc)},
            "检查磁盘空间与目录权限；或执行 sfx doctor 查看实际数据目录",
        ) from exc

    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=5000")
        conn.execute("PRAGMA synchronous=NORMAL")
        conn.execute("PRAGMA foreign_keys=ON")
    except sqlite3.Error as exc:
        conn.close()
        raise SfxError(
            E_STORE,
            f"数据库初始化失败：{db_path}",
            {"path": db_path, "reason": str(exc)},
            "该路径可能不是可写的 SQLite 数据库文件",
        ) from exc
    return conn


def close_db(conn: sqlite3.Connection | None) -> None:
    """静默关闭连接（``match`` 的快速路径上不允许因为关闭失败而报错）。"""
    if conn is None:
        return
    try:
        conn.close()
    except sqlite3.Error:
        pass
