"""``sfx prime`` —— 生成一段可直接粘贴给 Metis 的自包含指令块（ARCH §7.4 Tier C 逃生通道）。

背景
----
Metis 无法自动调用 skill。``sfx prime`` 是**零集成、零配置**的接入方式：
用户在命令行跑 ``sfx prime "<任务描述>"``，得到一段 Markdown 指令块，
把它粘贴到 Metis 对话开头，Metis 就会按指令去读指定 skill 的 SKILL.md 并执行。

这对应架构里的 Tier C（既不执行命令也不读约定文件时的兜底），
但同样适用于"用户不想配置约定文件、就想先试一下"的场景。

契约
----
- 输入：``--task <原文>`` 或位置参数（同 ``sfx match``）。
- 输出：信封 ``data.prompt`` 是一段**自包含**的 Markdown 指令文本；
  ``data.matched`` 是命中的路由卡（便于程序化消费）。
- **自包含性检查**：指令里不能要求 Metis 执行任何命令（Tier C 的前提就是不能执行）；
  只能要求它"读取指定文件并遵循"。
"""

from __future__ import annotations

import os

from sfx import _boot, _ids
from sfx import _errors as errors
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope
from sfx.core.model.event import CHANNEL_CLI

ALLOWED_FLAGS: frozenset[str] = frozenset({
    "task", "stdin", "top", "session", "project", "json", "human",
})


def _read_task(opts: dict[str, object], positional: list[str]) -> str:
    """取得任务描述原文（与 cmd_match 一致）。"""
    if dispatch.opt_bool(opts, "stdin"):
        try:
            import sys

            return sys.stdin.read()
        except OSError as exc:
            raise errors.SfxError(
                errors.E_USAGE, f"读取 stdin 失败：{exc}", {}, "改用 --task \"<任务描述>\" 传入"
            ) from exc
    task = dispatch.opt_str(opts, "task")
    if task is None and positional:
        task = " ".join(positional)
    if not task or not task.strip():
        raise errors.SfxError(
            errors.E_USAGE,
            "缺少任务描述",
            {"need": "--task <原文> | --stdin | 位置参数"},
            "示例：sfx prime \"生成一个像素游戏角色\"",
        )
    return task.strip()


def build_prime_prompt(task: str, cards: list[dict[str, object]]) -> str:
    """把任务 + 路由卡渲染成一段可粘贴给 Metis 的自包含指令块。

    关键约束（ARCH §7.4 自包含性检查）：
    - **绝不要求 Metis 执行任何命令**（Tier C 前提）；
    - 只要求"读取指定文件的 SKILL.md 并严格遵循"；
    - 指令里必须写清"如果读不到文件，就按你的通用能力回答，不要编造"。
    """
    lines: list[str] = []
    lines.append("请先阅读并严格遵循下面的技能指令，再完成我的任务。")
    lines.append("")
    lines.append("我的任务：")
    lines.append(f"> {task}")
    lines.append("")

    if not cards:
        lines.append("没有找到匹配的技能。请用你的通用能力直接完成上述任务，")
        lines.append("不要编造任何不存在的技能或文件。")
        return "\n".join(lines)

    lines.append("请在开始前，用你的文件读取能力打开并完整阅读下面列出的技能定义文件，")
    lines.append("然后严格按照该文件里的规则、工作流与产出规范来完成我的任务：")
    lines.append("")
    for idx, card in enumerate(cards, start=1):
        name = card.get("name", "")
        summary = card.get("summary", "")
        path = card.get("path", "")
        lines.append(f"{idx}. 技能「{name}」")
        if summary:
            lines.append(f"   摘要：{summary}")
        if path:
            lines.append(f"   定义文件路径（请直接打开阅读）：{path}")
        lines.append("")
    lines.append("注意事项：")
    lines.append("- 上面列出的路径是本机的绝对路径，请直接读取，不要臆测或改写。")
    lines.append("- 如果某个路径无法打开或文件不存在，跳过该技能，并如实说明，不要编造内容。")
    lines.append("- 严格遵守技能文件里的要求，不要自行省略其中的关键步骤。")
    return "\n".join(lines)


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """执行 prime：匹配 → 渲染可粘贴指令块。"""
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "prime")
    task = _read_task(opts, positional)

    from sfx.core.service import matcher, router, telemetry
    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    top = dispatch.opt_int(opts, "top")
    if top is not None and top > 0:
        cfg.top_n = top

    project_root = dispatch.opt_str(opts, "project") or os.getcwd()
    home = cfg.home

    warnings: list[str] = []
    conn = sqlite_open.open_db(pathx.db_path(home))
    try:
        migrator.migrate(conn, _boot.now_rfc3339())
        skills = skill_repo.SkillRepo(conn).list_active()
        history = event_repo.EventRepo(conn).history_scores()
        synonyms, synonym_warnings = matcher.load_synonyms(home, logger)
        warnings.extend(synonym_warnings)

        results = matcher.match(task, skills, cfg, history, synonyms)
        session_id = dispatch.opt_str(opts, "session") or _ids.uuid7()
        cards = router.build_route_card(results)

        # 埋点（失败不阻断）
        try:
            recorder = telemetry.Telemetry(event_repo.EventRepo(conn), logger)
            recorder.record_match(
                session_id=session_id,
                task=task,
                results=results,
                elapsed_ms=_boot.elapsed_ms(),
                engine_version=_engine_version(cfg),
                channel=CHANNEL_CLI,
                project_root=project_root,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warn("prime", "telemetry_failed", reason=type(exc).__name__)
    finally:
        sqlite_open.close_db(conn)

    prompt = build_prime_prompt(task, cards)
    code = errors.OK if results else errors.EMPTY_MATCH
    data = {
        "session_id": session_id,
        "matched": cards,
        "match_count": len(cards),
        "threshold": cfg.threshold,
        "engine_version": _engine_version(cfg),
        "prompt": prompt,
    }
    return Envelope.success(data=data, code=code, warnings=warnings, elapsed_ms=_boot.elapsed_ms())


def _engine_version(cfg) -> str:
    from sfx import ENGINE_VERSION

    if str(cfg.semantic).strip().lower() in ("bm25", "onnx"):
        return "rule+bm25+v1"
    return ENGINE_VERSION
