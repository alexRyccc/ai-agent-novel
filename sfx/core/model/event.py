"""领域对象：Session 与 CallEvent（ARCH §4.3 ``sessions`` / ``call_events``）。

隐私纪律（ARCH §10.3 / NFR-04 ③）
---------------------------------
``sessions`` **不存任务正文**，只存 ``task_hash``（FNV-1a）与 ``task_len``：
- 埋点是"调用效果"的统计来源，不需要原文；
- 日志与库里一旦出现正文，就会变成内部信息外泄面（内部规范、代码片段都可能出现在任务描述里）。

所以这里刻意**没有** ``task_text`` 字段——这不是遗漏，是设计。
"""

from __future__ import annotations

import json

#: 事件类型枚举（ARCH §10.4：常量集中）
EVENT_MATCH = "match"
EVENT_LOAD = "load"
EVENT_FEEDBACK = "feedback"
EVENT_RATE = "rate"

#: 通道枚举
CHANNEL_CLI = "cli"
CHANNEL_CONV = "conv"
CHANNEL_WEB = "web"
CHANNEL_MANUAL = "manual"
CHANNEL_PRIME = "prime"


class Session:
    """一次 ``sfx match`` 调用的会话记录。

    （与 :class:`~sfx.core.model.skill.Skill` 同理，这里不用 ``@dataclass``：
      ``dataclasses`` 会连带拉起 ``inspect``/``ast``/``dis``，实测 +38.6ms，
      ``sfx match`` 热路径付不起。详见 skill.py 的说明。）
    """

    __slots__ = (
        "id", "task_hash", "task_len", "channel", "project_root",
        "match_count", "top_score", "top_skill_id", "created_at",
    )

    def __init__(
        self,
        id: str = "",
        task_hash: str = "",
        task_len: int = 0,
        channel: str = CHANNEL_CLI,
        project_root: str = "",
        match_count: int = 0,
        top_score: float = 0.0,
        top_skill_id: str = "",
        created_at: str = "",
    ) -> None:
        self.id = id
        self.task_hash = task_hash
        self.task_len = task_len
        self.channel = channel
        self.project_root = project_root
        self.match_count = match_count
        self.top_score = top_score
        self.top_skill_id = top_skill_id
        self.created_at = created_at

    def to_row(self) -> tuple:
        """转成 ``sessions`` 表的插入参数元组。"""
        return (
            self.id,
            self.task_hash,
            self.task_len,
            self.channel,
            self.project_root,
            self.match_count,
            self.top_score,
            self.top_skill_id,
            self.created_at,
        )


class CallEvent:
    """一条调用事件（match / load / feedback …）。

    （同样不用 ``@dataclass``，理由见 :class:`~sfx.core.model.skill.Skill`。）
    """

    __slots__ = (
        "id", "session_id", "skill_id", "type", "rank", "score",
        "elapsed_ms", "engine_version", "channel", "payload", "created_at",
    )

    def __init__(
        self,
        id: str = "",
        session_id: str = "",
        skill_id: str = "",
        type: str = EVENT_MATCH,
        rank: int = 0,
        score: float = 0.0,
        elapsed_ms: int = 0,
        engine_version: str = "",
        channel: str = CHANNEL_CLI,
        payload: dict[str, object] | None = None,
        created_at: str = "",
    ) -> None:
        self.id = id
        self.session_id = session_id
        self.skill_id = skill_id
        self.type = type
        self.rank = rank
        self.score = score
        self.elapsed_ms = elapsed_ms
        self.engine_version = engine_version
        self.channel = channel
        self.payload = payload if payload is not None else {}
        self.created_at = created_at

    def to_row(self) -> tuple:
        """转成 ``call_events`` 表的插入参数元组。"""
        try:
            payload_json = json.dumps(self.payload, ensure_ascii=False)
        except (TypeError, ValueError):
            payload_json = "{}"
        return (
            self.id,
            self.session_id,
            self.skill_id,
            self.type,
            self.rank,
            self.score,
            self.elapsed_ms,
            self.engine_version,
            self.channel,
            payload_json,
            self.created_at,
        )
