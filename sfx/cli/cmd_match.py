"""``sfx match`` —— 最热路径（ARCH §5.2 / NFR-05）。

契约（冻结项）
--------------
- 输入：``--task <原文>`` 或 ``--stdin``（二者选一），也接受**位置参数**形式
  ``sfx match "<任务描述>"``（验收项 3 用的就是这种写法）；
- 输出 ``data``：``session_id`` / ``matched[{skill_id,name,summary,path,score,reason}]`` /
  ``match_count`` / ``threshold`` / ``engine_version``；
- 无命中时 ``matched=[]`` 但**仍返回 ``session_id``**，``ok=true``，``code=EMPTY_MATCH``；
- **路由卡绝不包含 skill 正文**（由 ``router.assert_route_card`` 的 golden 断言守住）。

模块顶层只 import 极轻量模块；``sqlite3`` / ``json`` 等在 :func:`run` 内按需导入，
保证 ``sfx --help`` 与未知命令路径的启动代价最小。
"""

from __future__ import annotations

import os
import sys

from sfx import _boot, _ids
from sfx import _errors as errors
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope
from sfx.core.model.event import CHANNEL_CLI

ALLOWED_FLAGS: frozenset[str] = frozenset({
    "task", "stdin", "top", "session", "project", "json", "human",
    "explain", "min-score",
})


def _read_task(opts: dict[str, object], positional: list[str]) -> str:
    """取得任务描述原文。

    Raises:
        SfxError: ``E_USAGE`` —— 三种输入方式都没给。
    """
    if dispatch.opt_bool(opts, "stdin"):
        try:
            return sys.stdin.read()
        except OSError as exc:
            raise errors.SfxError(
                errors.E_USAGE,
                f"读取 stdin 失败：{exc}",
                {},
                "改用 --task \"<任务描述>\" 传入",
            ) from exc
    task = dispatch.opt_str(opts, "task")
    if task is None and positional:
        task = " ".join(positional)
    if not task or not task.strip():
        raise errors.SfxError(
            errors.E_USAGE,
            "缺少任务描述",
            {"need": "--task <原文> | --stdin | 位置参数"},
            "示例：sfx match \"帮我重构这段数据库访问代码\"",
        )
    return task.strip()


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """执行一次匹配。

    Args:
        cfg: :class:`~sfx.infra.conf.Config`。
        logger: 日志器。
        opts: 选项字典。
        positional: 位置参数（可直接作为任务描述）。

    Returns:
        :class:`Envelope`。
    """
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "match")
    task = _read_task(opts, positional)

    # ---- 延迟导入：热路径必需，但 --help 等路径不该付 ----
    from sfx.core.service import matcher, router, telemetry
    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    top = dispatch.opt_int(opts, "top")
    if top is not None and top > 0:
        cfg.top_n = top  # 命令行 flag 优先级最高（§10.1）

    min_score_raw = dispatch.opt_str(opts, "min-score")
    if min_score_raw is not None:
        try:
            cfg.threshold = float(min_score_raw)
        except ValueError:
            raise errors.SfxError(
                errors.E_USAGE,
                f"min-score 必须是数字：{min_score_raw}",
                {"min-score": min_score_raw},
                "示例：sfx match --min-score 0.5 \"帮我写一个接口\"",
            )

    project_root = dispatch.opt_str(opts, "project") or ""
    if not project_root:
        try:
            project_root = os.getcwd()
        except OSError:
            project_root = ""

    warnings: list[str] = []
    home = cfg.home

    ok = True
    # 只读一次库：读 skill 与写埋点**复用同一条连接**。
    # 实测在 Windows 上 ``sqlite3.connect`` + 3 个 PRAGMA 的开销是十几毫秒级，
    # 打开两次等于白付一倍，对 300ms 预算是实打实的浪费。
    conn = sqlite_open.open_db(pathx.db_path(home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        skills = skill_repo.SkillRepo(conn).list_active()
        history = event_repo.EventRepo(conn).history_scores()

        synonyms, synonym_warnings = matcher.load_synonyms(home, logger)
        warnings.extend(synonym_warnings)

        explain = None
        if dispatch.opt_bool(opts, "explain"):
            results, explain = matcher.match_explain(task, skills, cfg, history, synonyms)
        else:
            results = matcher.match(task, skills, cfg, history, synonyms)
        session_id = dispatch.opt_str(opts, "session") or _ids.uuid7()

        # ---- 埋点：失败绝不阻断主返回（NFR-07 E-4）----
        elapsed_ms = _boot.elapsed_ms()
        try:
            recorder = telemetry.Telemetry(event_repo.EventRepo(conn), logger)
            ok = recorder.record_match(
                session_id=session_id,
                task=task,
                results=results,
                elapsed_ms=elapsed_ms,
                engine_version=cfg_engine_version(cfg),
                channel=CHANNEL_CLI,
                project_root=project_root,
            )
        except Exception as exc:  # noqa: BLE001 - 埋点整体失败也只是降级
            ok = False
            logger.warn("match", "telemetry_failed", reason=type(exc).__name__)
    finally:
        sqlite_open.close_db(conn)
    if not ok:
        warnings.append("埋点写入失败，已降级：匹配结果不受影响")

    code = errors.OK if results else errors.EMPTY_MATCH
    data = router.build_match_data(
        session_id=session_id,
        results=results,
        threshold=cfg.threshold,
        engine_version=cfg_engine_version(cfg),
    )
    data["task_len"] = len(task)
    data["skills_considered"] = len(skills)
    if explain is not None:
        data["explain"] = explain

    return Envelope.success(
        data=data, code=code, warnings=warnings, elapsed_ms=_boot.elapsed_ms()
    )


def cfg_engine_version(cfg) -> str:
    """根据配置里的 ``semantic`` 开关如实上报引擎标识。

    WS-2 只有 ``off``，因此恒定 ``rule+dict+v1``；未来接入 BM25 后会自动变成
    ``rule+bm25+v1``（ARCH §7.2.2）。**绝不谎报尚未启用的引擎**。
    """
    from sfx import ENGINE_VERSION

    if str(cfg.semantic).strip().lower() in ("bm25", "onnx"):
        return "rule+bm25+v1"
    return ENGINE_VERSION
