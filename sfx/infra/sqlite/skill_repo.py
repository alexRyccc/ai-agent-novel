"""``skills`` 表 Repository（ARCH §4.3 / D-1~D-5）。

唯一性与幂等
------------
``UNIQUE(source_root, dir_path)`` 保证**重复扫描不产生重复记录**（FR-01）。
``upsert`` 的三种返回：``added`` / ``updated`` / ``unchanged``，
其中 ``unchanged`` 只更新 ``last_scanned_at``，不动 ``updated_at``——
这样"扫一遍什么都没变"不会让所有 skill 的时间戳集体漂移。

D-1 纪律：不使用 ``INSERT OR REPLACE``，一律显式 ``SELECT`` 后 ``UPDATE``/``INSERT``。
"""

from __future__ import annotations

import sqlite3

from sfx.core.model.skill import STATUS_ACTIVE, Skill

_COLUMNS = (
    "id", "name", "slug", "summary", "description", "source_root", "dir_path",
    "entry_path", "author", "version", "status", "content_hash", "body_bytes",
    "triggers_json", "tags_json", "summary_fallback",
    "created_at", "updated_at", "last_scanned_at",
)

_SELECT_COLS = ", ".join(_COLUMNS)
_INSERT_SQL = (
    "INSERT INTO skills (" + ", ".join(_COLUMNS) + ") VALUES ("
    + ", ".join("?" for _ in _COLUMNS) + ")"
)

#: 状态常量集中（ARCH §10.4）
ADDED = "added"
UPDATED = "updated"
UNCHANGED = "unchanged"


class SkillRepo:
    """``skills`` 表的读写封装。"""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---------------- 查询 ----------------
    def find_key(self, source_root: str, dir_path: str) -> tuple[str, str] | None:
        """按 ``(source_root, dir_path)`` 查找已有记录。

        Returns:
            ``(id, content_hash)``，不存在时 ``None``。
        """
        row = self._conn.execute(
            "SELECT id, content_hash FROM skills WHERE source_root = ? AND dir_path = ?",
            (source_root, dir_path),
        ).fetchone()
        if row is None:
            return None
        return (str(row[0]), str(row[1] or ""))

    def list_active(self) -> list[Skill]:
        """返回全部 ``status='active'`` 的 skill（不含正文）。"""
        rows = self._conn.execute(
            f"SELECT {_SELECT_COLS} FROM skills WHERE status = ? ORDER BY slug",
            (STATUS_ACTIVE,),
        ).fetchall()
        return [Skill.from_row(row) for row in rows]

    def count(self, status: str | None = None) -> int:
        """计数；``status=None`` 时统计全部。"""
        if status is None:
            row = self._conn.execute("SELECT COUNT(*) FROM skills").fetchone()
        else:
            row = self._conn.execute(
                "SELECT COUNT(*) FROM skills WHERE status = ?", (status,)
            ).fetchone()
        return int(row[0]) if row else 0

    def last_scanned_at(self) -> str:
        """最近一次扫描时间（库空时返回空串）。``MAX`` 是标准 SQL 聚合，遵守 D-2。"""
        row = self._conn.execute("SELECT MAX(last_scanned_at) FROM skills").fetchone()
        if row is None or row[0] is None:
            return ""
        return str(row[0])

    # ---------------- 写入 ----------------
    def upsert(self, skill: Skill) -> str:
        """插入或更新一条 skill。

        Returns:
            ``"added"`` / ``"updated"`` / ``"unchanged"``
        """
        existing = self.find_key(skill.source_root, skill.dir_path)
        if existing is None:
            self._insert(skill)
            return ADDED
        skill_id, old_hash = existing
        if old_hash and old_hash == skill.content_hash:
            self._touch(skill_id, skill.last_scanned_at)
            return UNCHANGED
        skill.id = skill_id
        self._update(skill)
        return UPDATED

    def _insert(self, skill: Skill) -> None:
        """插入新记录。``slug`` 撞 UNIQUE 时追加内容 hash 前缀重试一次。"""
        try:
            self._conn.execute(_INSERT_SQL, skill.to_row())
        except sqlite3.IntegrityError:
            skill.slug = f"{skill.slug}-{skill.content_hash[:6]}"
            self._conn.execute(_INSERT_SQL, skill.to_row())

    def repair_ids(self) -> int:
        """修复主键为空/异常的历史行，返回修复条数。

        为什么需要：``skills.id`` 是 uuidv7 主键，但早期版本曾以 ``""`` 落库
        （解析器分配 id 之前的实现）。这类行在**所有按 id 关联的地方都是隐形人**：
        埋点统计 join 不上、看板上永远"数据不足"、路由卡的 ``skill_id`` 是空串。
        表现是"这个技能明明存在却怎么都不对"，排查成本极高。
        扫描是唯一会遍历全表的机会，顺手把数据修回来，比留一条迁移脚本更可靠。
        """
        rows = self._conn.execute(
            "SELECT rowid FROM skills WHERE id IS NULL OR length(id) <> 36"
        ).fetchall()
        if not rows:
            return 0
        from sfx import _ids

        for (rowid,) in rows:
            self._conn.execute(
                "UPDATE skills SET id = ? WHERE rowid = ?", (_ids.uuid7(), int(rowid))
            )
        return len(rows)

    def _update(self, skill: Skill) -> None:
        """更新已有记录（不含 ``created_at``）。"""
        self._conn.execute(
            "UPDATE skills SET name=?, slug=?, summary=?, description=?, source_root=?,"
            " dir_path=?, entry_path=?, author=?, version=?, status=?, content_hash=?,"
            " body_bytes=?, triggers_json=?, tags_json=?, summary_fallback=?,"
            " updated_at=?, last_scanned_at=? WHERE id=?",
            (
                skill.name, skill.slug, skill.summary, skill.description,
                skill.source_root, skill.dir_path, skill.entry_path, skill.author,
                skill.version, skill.status, skill.content_hash, skill.body_bytes,
                skill.to_row()[13], skill.to_row()[14],
                1 if skill.summary_fallback else 0,
                skill.updated_at, skill.last_scanned_at, skill.id,
            ),
        )

    def _touch(self, skill_id: str, scanned_at: str) -> None:
        """内容未变：只刷新扫描时间，不动 ``updated_at``（避免时间戳无意义漂移）。"""
        self._conn.execute(
            "UPDATE skills SET last_scanned_at=? WHERE id=?", (scanned_at, skill_id)
        )

    def commit(self) -> None:
        """提交事务（扫描结束时由调用方统一提交一次，避免逐条 fsync）。"""
        self._conn.commit()
