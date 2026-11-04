"""``sfx load`` —— 上报一次"采纳"，闭合准确率漏斗（ARCH §7.2 的 AdoptionRate 分子）。

为什么需要这个命令
------------------
看板上的"采纳率"= 被采纳次数 / 被推荐次数。没有 ``load`` 事件时分子恒为 0，
于是 ``history_scores`` 按设计返回空字典（信号不可用），页面只能一直显示"数据不足"。
换句话说：**没有这条上报通道，准确率在数学上不可能有值**，页面做得再漂亮也只是空壳。

设计取舍
--------
- **不自动推断**：不根据"用户跑了 match 之后又打开了文件"去猜采纳。猜出来的 AdoptionRate
  进了排序就会自我强化（推荐越多→猜得越多→越推越多），最后分数好看但没有意义。
  采纳必须由使用者显式上报一次，成本是敲一行命令。
- **可归因**：默认挂到最近一次 ``match`` 的会话上，让"这次推荐的"和"这次采纳的"能对上；
  ``--session`` 可显式指定。
- **幂等性不做**：同一个人重复 load 同一个技能会被计两次。这是有意的——真实采纳次数
  本来就可能是多次（每次任务都用这个技能），去重反而会低估高频技能。
"""

from __future__ import annotations

import os

from sfx import _boot
from sfx import _errors as errors
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope
from sfx.core.model.event import CHANNEL_CLI

ALLOWED_FLAGS: frozenset[str] = frozenset({
    "skill", "session", "note", "project", "engine", "json", "human",
    "undo", "misfire",
})


def _names_of(skill) -> list[str]:
    """一个技能能被"叫出来"的所有写法。

    目录名必须算一个：用户在文件管理器里看到的是 ``order-api/``，
    但入库后的 ``slug`` 可能被去重逻辑改成 ``order-api-a1b2c3``。
    只认 slug 的话，用户照着自己看到的目录名敲命令会得到"找不到"，
    而他明明看着那个文件夹 —— 这种失败最消耗信任。
    """
    names = [skill.slug, skill.name or "", skill.id]
    if skill.dir_path:
        names.append(os.path.basename(os.path.normpath(skill.dir_path)))
    return [n for n in names if n]


def _resolve_skill(cfg, needle: str):
    """按 slug / name / 目录名 / id 找技能。找不到抛 ``E_NOT_FOUND``。"""
    from sfx.infra import pathx
    from sfx.infra.sqlite import migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        skills = [s for s in skill_repo.SkillRepo(conn).list_active()]
    finally:
        sqlite_open.close_db(conn)

    key = needle.strip()
    low = key.lower()
    exact = [s for s in skills if any(n == key for n in _names_of(s))]
    if exact:
        return exact[0]
    fuzzy = [s for s in skills if low and any(low in n.lower() for n in _names_of(s))]
    if len(fuzzy) == 1:
        return fuzzy[0]
    if len(fuzzy) > 1:
        raise errors.SfxError(
            errors.E_USAGE,
            f"「{key}」匹配到 {len(fuzzy)} 个技能，无法确定是哪一个",
            {"candidates": [s.slug for s in fuzzy[:8]]},
            "用完整的 slug 再试一次：" + "、".join(s.slug for s in fuzzy[:3]),
        )
    raise errors.SfxError(
        errors.E_NOT_FOUND,
        f"找不到技能「{key}」",
        {"needle": key},
        "先跑 sfx scan 让技能入库，或用 sfx match 确认准确的 slug",
    )


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """记录一次 load 事件并返回更新后的计数。"""
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "load")

    needle = dispatch.opt_str(opts, "skill") or (positional[0] if positional else "")
    if not needle.strip():
        raise errors.SfxError(
            errors.E_USAGE,
            "缺少要上报采纳的技能",
            {},
            'sfx load <slug>，例如：sfx load java-spring-boot-api',
        )

    from sfx.core.service import telemetry
    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    undo = dispatch.opt_bool(opts, "undo")
    misfire = dispatch.opt_bool(opts, "misfire")
    if undo and misfire:
        raise errors.SfxError(
            errors.E_USAGE,
            "--undo 与 --misfire 不能同时使用",
            {},
            "一次只做一件事：撤销用 --undo，标记误推荐用 --misfire",
        )

    skill = _resolve_skill(cfg, needle)
    note = dispatch.opt_str(opts, "note") or ""
    project_root = dispatch.opt_str(opts, "project") or os.getcwd()

    warnings: list[str] = []
    conn = sqlite_open.open_db(pathx.db_path(cfg.home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        events = event_repo.EventRepo(conn)

        if undo:
            # 撤销最近一次 load：只删 load 事件，回读计数让调用方立刻看到变化
            removed = events.undo_last_load(skill.id)
            counts = events.scoreboard().get(skill.id, {})
            data = {
                "skill_id": skill.id,
                "slug": skill.slug,
                "name": skill.name,
                "undo": True,
                "removed": removed,
                "shown": int(counts.get("shown", 0)),
                "loaded": int(counts.get("loaded", 0)),
                "feedback": int(counts.get("feedback", 0)),
                "project_root": project_root,
            }
            return Envelope.success(data, warnings=warnings, elapsed_ms=_boot.elapsed_ms())

        session_id = dispatch.opt_str(opts, "session") or events.latest_session_id()
        if not session_id:
            # 没有历史会话（用户还没跑过 match 就手动 load）——用临时会话兜住，
            # 保证这条采纳**不丢**。它不参与任何推荐归因，但计数是真实的。
            from sfx import _ids

            session_id = _ids.uuid7()
            warnings.append("no_prior_match_session")

        recorder = telemetry.Telemetry(events, logger)

        if misfire:
            # 标记误推荐：写 feedback 事件（只进统计，绝不进 history_scores 排序）
            ok = recorder.record_feedback(
                session_id=session_id,
                skill_id=skill.id,
                kind="misfire",
                note=note,
                channel=CHANNEL_CLI,
            )
            if not ok:
                raise errors.SfxError(
                    errors.E_STORE,
                    "反馈事件写入失败（数据库异常）",
                    {"skill": skill.slug},
                    "检查数据目录写权限；本次反馈未计入统计",
                )
            counts = events.scoreboard().get(skill.id, {})
            data = {
                "skill_id": skill.id,
                "slug": skill.slug,
                "name": skill.name,
                "session_id": session_id,
                "recorded": True,
                "kind": "misfire",
                "shown": int(counts.get("shown", 0)),
                "loaded": int(counts.get("loaded", 0)),
                "feedback": int(counts.get("feedback", 0)),
                "project_root": project_root,
            }
            return Envelope.success(data, warnings=warnings, elapsed_ms=_boot.elapsed_ms())

        ok = recorder.record_load(
            session_id=session_id,
            skill_id=skill.id,
            engine_version=dispatch.opt_str(opts, "engine") or "",
            channel=CHANNEL_CLI,
            note=note,
        )
        if not ok:
            raise errors.SfxError(
                errors.E_STORE,
                "采纳事件写入失败（数据库异常）",
                {"skill": skill.slug},
                "检查数据目录写权限；本次采纳未计入统计",
            )

        # 回读本次技能的累计计数，让调用方立刻看到漏斗位置
        counts = event_repo.EventRepo(conn).scoreboard().get(skill.id, {})
        shown = int(counts.get("shown", 0))
        loaded = int(counts.get("loaded", 0))
        min_sample = 5
        rate = round(min(1.0, loaded / float(shown)), 4) if shown >= min_sample else None

        data = {
            "skill_id": skill.id,
            "slug": skill.slug,
            "name": skill.name,
            "session_id": session_id,
            "recorded": True,
            "shown": shown,
            "loaded": loaded,
            "load_rate": rate,
            "min_sample": min_sample,
            "project_root": project_root,
        }
        return Envelope.success(data, warnings=warnings, elapsed_ms=_boot.elapsed_ms())
    finally:
        sqlite_open.close_db(conn)
