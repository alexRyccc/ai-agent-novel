"""最小埋点：写 ``sessions`` 与 ``call_events``（ARCH §12.6.2 WS-2 W2-5）。

铁律（NFR-07 **E-4**）
---------------------
**埋点失败绝不阻断主返回**。``match`` 的结果先算出来；写库失败只记录 warn 日志，
信封数据照常返回（并在 ``warnings[]`` 里附一条降级说明）。
本模块的每个公开方法都保证**不向外抛异常**。

隐私（ARCH §10.3 / NFR-04 ③）
----------------------------
只落 ``task_hash``（FNV-1a）与 ``task_len``，**不落任务正文**；日志里同样只记 hash。
"""

from __future__ import annotations

from sfx import _boot, _ids
from sfx.core.model.event import (
    CHANNEL_CLI,
    EVENT_FEEDBACK,
    EVENT_LOAD,
    EVENT_MATCH,
    CallEvent,
    Session,
)


class Telemetry:
    """埋点写入器。"""

    __slots__ = ("_repo", "_logger")

    def __init__(self, repo, logger) -> None:
        """
        Args:
            repo: :class:`~sfx.infra.sqlite.event_repo.EventRepo`（或同构对象）。
            logger: 日志器。
        """
        self._repo = repo
        self._logger = logger

    # ------------------------------------------------------------------
    def record_match(
        self,
        session_id: str,
        task: str,
        results,
        elapsed_ms: int,
        engine_version: str,
        channel: str = CHANNEL_CLI,
        project_root: str = "",
    ) -> bool:
        """记录一次 ``match``：一条 session + N 条 ``match`` 事件。

        Returns:
            ``True`` 成功；``False`` 表示已降级（调用方应往 ``warnings`` 追加说明）。
        """
        now_text = _boot.now_rfc3339()
        top_score = float(results[0].score) if results else 0.0
        top_skill_id = results[0].skill_id if results else ""
        session = Session(
            id=session_id,
            task_hash=_ids.fnv1a_hex(task),
            task_len=len(task),
            channel=channel,
            project_root=project_root,
            match_count=len(results),
            top_score=top_score,
            top_skill_id=top_skill_id,
            created_at=now_text,
        )
        events = [
            CallEvent(
                id=_ids.uuid7(),
                session_id=session_id,
                skill_id=result.skill_id,
                type=EVENT_MATCH,
                rank=index + 1,
                score=float(result.score),
                elapsed_ms=elapsed_ms,
                engine_version=engine_version,
                channel=channel,
                payload={"reason": result.reason[:120]},
                created_at=now_text,
            )
            for index, result in enumerate(results)
        ]
        try:
            self._repo.insert_session(session)
            self._repo.insert_events(events)
            self._repo.commit()
        except Exception as exc:  # noqa: BLE001 - E-4：绝不阻断主返回
            self._logger.warn(
                "telemetry", "record_failed",
                session=session_id, reason=type(exc).__name__,
            )
            return False
        self._logger.info(
            "telemetry", "match_recorded",
            session=session_id, match_count=len(results),
            top_score=round(top_score, 4), elapsed_ms=elapsed_ms,
        )
        return True

    def record_load(
        self,
        session_id: str,
        skill_id: str,
        rank: int = 0,
        score: float = 0.0,
        elapsed_ms: int = 0,
        engine_version: str = "",
        channel: str = CHANNEL_CLI,
        note: str = "",
    ) -> bool:
        """记录一次 ``load``（= 采纳），漏斗的第二层。

        为什么必须有这个入口：SkillScore 的分母是"被推荐次数"，分子是"被采纳次数"。
        只要没有 ``load`` 事件，采纳率在数学上永远是"分母有、分子零"，
        ``history_scores`` 也会按设计返回空字典（信号不可用），
        于是整个"准确率"页面只能一直显示"数据不足"——**闭环是产品能不能自证的关键**。

        与 :meth:`record_match` 一致：写失败只记 warn 并返回 ``False``，
        绝不让埋点故障影响用户的正常操作（NFR-07 E-4）。
        """
        event = CallEvent(
            id=_ids.uuid7(),
            session_id=session_id,
            skill_id=skill_id,
            type=EVENT_LOAD,
            rank=int(rank),
            score=float(score),
            elapsed_ms=int(elapsed_ms),
            engine_version=engine_version,
            channel=channel,
            payload={"note": note[:120]} if note else {},
            created_at=_boot.now_rfc3339(),
        )
        try:
            self._repo.insert_events([event])
            self._repo.commit()
        except Exception as exc:  # noqa: BLE001 - E-4：绝不阻断主返回
            self._logger.warn(
                "telemetry", "load_record_failed",
                session=session_id, skill=skill_id, reason=type(exc).__name__,
            )
            return False
        self._logger.info(
            "telemetry", "load_recorded", session=session_id, skill=skill_id,
        )
        return True

    def record_feedback(
        self,
        session_id: str,
        skill_id: str,
        kind: str,
        note: str = "",
        channel: str = CHANNEL_CLI,
    ) -> bool:
        """记录一条 ``feedback`` 事件（= 误推荐等人工反馈）。

        与 :meth:`record_load` 一致：写失败只记 warn 并返回 ``False``（NFR-07 E-4）。
        ``feedback`` 只进统计（``scoreboard``），**绝不进 ``history_scores``**——
        后者 ``WHERE type IN ('match','load')`` 天然排除它，排序信号不受污染。
        """
        payload: dict[str, object] = {"kind": kind}
        if note:
            payload["note"] = note[:120]
        event = CallEvent(
            id=_ids.uuid7(),
            session_id=session_id,
            skill_id=skill_id,
            type=EVENT_FEEDBACK,
            rank=0,
            score=0.0,
            elapsed_ms=0,
            engine_version="",
            channel=channel,
            payload=payload,
            created_at=_boot.now_rfc3339(),
        )
        try:
            self._repo.insert_events([event])
            self._repo.commit()
        except Exception as exc:  # noqa: BLE001 - E-4：绝不阻断主返回
            self._logger.warn(
                "telemetry", "feedback_record_failed",
                session=session_id, skill=skill_id, reason=type(exc).__name__,
            )
            return False
        self._logger.info(
            "telemetry", "feedback_recorded",
            session=session_id, skill=skill_id, kind=kind,
        )
        return True
