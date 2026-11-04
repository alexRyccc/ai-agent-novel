"""``sessions`` / ``call_events`` 表 Repository（ARCH §4.3）。

埋点写入失败**绝不阻断主返回**（NFR-07 E-4）：所有方法抛出的 ``sqlite3.Error``
由 ``core.service.telemetry`` 捕获并记录 warn 日志，``sfx match`` 的数据照常返回。

``history_scores`` 是 matcher 的 history 信号来源：
返回 ``{skill_id: load_rate}``；**当库里一条 ``load`` 事件都没有时返回空字典**，
语义是"该信号不可用"→ matcher 会把 ``weights.history`` 按比例摊还到其它信号
（ARCH §12.6.2.1 **C-1** 与 §7.2.3）。WS 阶段没有 ``sfx load`` 命令，
所以这里恒定返回空字典，代码路径与未来的 Tier B 完全一致。
"""

from __future__ import annotations

import sqlite3

from sfx.core.model.event import CallEvent, Session

_SESSION_COLS = (
    "id", "task_hash", "task_len", "channel", "project_root",
    "match_count", "top_score", "top_skill_id", "created_at",
)
_EVENT_COLS = (
    "id", "session_id", "skill_id", "type", "rank", "score",
    "elapsed_ms", "engine_version", "channel", "payload_json", "created_at",
)


class EventRepo:
    """埋点表的读写封装。"""

    __slots__ = ("_conn",)

    def __init__(self, conn: sqlite3.Connection) -> None:
        self._conn = conn

    # ---------------- 写入 ----------------
    def insert_session(self, session: Session) -> None:
        """写入一条会话记录。"""
        self._conn.execute(
            "INSERT INTO sessions (" + ", ".join(_SESSION_COLS) + ") VALUES ("
            + ", ".join("?" for _ in _SESSION_COLS) + ")",
            session.to_row(),
        )

    def insert_events(self, events: list[CallEvent]) -> None:
        """批量写入调用事件（``executemany``，一条语句搞定）。"""
        if not events:
            return
        self._conn.executemany(
            "INSERT INTO call_events (" + ", ".join(_EVENT_COLS) + ") VALUES ("
            + ", ".join("?" for _ in _EVENT_COLS) + ")",
            [event.to_row() for event in events],
        )

    def commit(self) -> None:
        """提交事务。"""
        self._conn.commit()

    def undo_last_load(self, skill_id: str) -> int:
        """删除该技能最近一条 ``load`` 事件（按 ``rowid DESC`` 取第一条）。

        用于 ``sfx load <slug> --undo``：把一次误上报的采纳撤回。
        只删 ``load`` 事件，不碰 ``match``（推荐分母）与 ``feedback``。

        Returns:
            实际删除的行数（``0`` 表示没有可撤销的 load）。
        """
        cursor = self._conn.execute(
            "DELETE FROM call_events WHERE rowid = ("
            " SELECT rowid FROM call_events WHERE type = 'load' AND skill_id = ?"
            " ORDER BY rowid DESC LIMIT 1)",
            (skill_id,),
        )
        self._conn.commit()
        return int(cursor.rowcount)

    # ---------------- 查询 ----------------
    def count_events(self) -> int:
        """``call_events`` 总行数（供 ``sfx doctor`` 展示）。"""
        row = self._conn.execute("SELECT COUNT(*) FROM call_events").fetchone()
        return int(row[0]) if row else 0

    def count_sessions(self) -> int:
        """``sessions`` 总行数。"""
        row = self._conn.execute("SELECT COUNT(*) FROM sessions").fetchone()
        return int(row[0]) if row else 0

    def latest_session_id(self) -> str:
        """最近一次 ``match`` 的会话 id；没有任何会话时返回空串。

        ``sfx load`` 用它把"采纳"挂回"推荐"，这样同一次推荐与采纳才能在漏斗里对上。

        排序为什么不能只按 ``created_at``：时间戳精度到秒，同一秒内连跑两次 match
        会得到两条相同时间，``ORDER BY created_at DESC LIMIT 1`` 取哪条是未定义的
        （实测会取到较早那条，导致采纳挂到了上一次会话）。加 ``rowid DESC`` 作为
        稳定的次级排序键，语义变成"最后写入的那条"。
        """
        row = self._conn.execute(
            "SELECT id FROM sessions ORDER BY created_at DESC, rowid DESC LIMIT 1"
        ).fetchone()
        return str(row[0]) if row else ""

    def history_scores(self) -> dict[str, float]:
        """计算每个 skill 的 history 信号（load_rate = load 次数 / match 次数）。

        Returns:
            ``{skill_id: 0.0~1.0}``；**没有任何 ``load`` 事件时返回空字典**，
            表示"信号不可用"，由 matcher 做权重摊还。

        说明：``GROUP BY`` + ``COUNT`` 是标准 SQL，不违反 D-2（禁的是 ``strftime``
        这类方言函数）。聚合逻辑本身放在 Python 侧，保持跨库可移植。
        """
        rows = self._conn.execute(
            "SELECT skill_id, type, COUNT(*) FROM call_events"
            " WHERE type IN ('match', 'load') GROUP BY skill_id, type"
        ).fetchall()
        if not rows:
            return {}

        matches: dict[str, int] = {}
        loads: dict[str, int] = {}
        for skill_id, event_type, count in rows:
            key = str(skill_id)
            number = int(count)
            if str(event_type) == "match":
                matches[key] = matches.get(key, 0) + number
            else:
                loads[key] = loads.get(key, 0) + number

        if not loads:
            # 闭环还没跑通（WS 阶段没有 sfx load）：history 信号不可用
            return {}

        scores: dict[str, float] = {}
        for skill_id, match_count in matches.items():
            if match_count <= 0:
                continue
            rate = loads.get(skill_id, 0) / float(match_count)
            scores[skill_id] = 0.0 if rate < 0.0 else (1.0 if rate > 1.0 else rate)
        return scores

    def scoreboard(self) -> dict[str, dict[str, int]]:
        """每个 skill 的原始计数：``{skill_id: {"shown": n, "loaded": m, "feedback": k}}``。

        与 :meth:`history_scores` 的区别在**要不要做除法**：

        - ``history_scores`` 是给 matcher 用的信号，没有 ``load`` 事件时返回空字典
          表示"信号不可用"，让 matcher 摊还权重 —— 它必须能表达"无数据"。
        - ``scoreboard`` 是给看板用的**原始证据**，不能在这里把"没数据"算成 0 分；
          换算成比率、以及在样本不足时拒绝对外展示比率，都是展示层的决定
          （见 ``cmd_serve._build_scores``）。把这两件事分开，才能保证
          "库里真有一条数据"和"库里一条数据都没有"在界面上不会被混成同一个 0。
        """
        rows = self._conn.execute(
            "SELECT skill_id, type, COUNT(*) FROM call_events"
            " WHERE type IN ('match', 'load', 'feedback') GROUP BY skill_id, type"
        ).fetchall()
        out: dict[str, dict[str, int]] = {}
        for skill_id, event_type, count in rows:
            key = str(skill_id)
            slot = out.setdefault(key, {"shown": 0, "loaded": 0, "feedback": 0})
            if str(event_type) == "match":
                slot["shown"] += int(count)
            elif str(event_type) == "load":
                slot["loaded"] += int(count)
            else:
                slot["feedback"] += int(count)
        return out
