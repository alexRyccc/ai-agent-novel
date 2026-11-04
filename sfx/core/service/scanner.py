"""多来源 skill 扫描（ARCH §3.2 / WS-2 W2-1 / FR-01）。

行为约定
--------
1. **来源目录不存在就跳过，不报错**——用户机器上往往只装了其中一两个工具；
2. **重复扫描不产生重复记录**——唯一键 ``(source_root, dir_path)`` + 内容 hash 比对
   （内容不变只刷新 ``last_scanned_at``，不产生新行）；
3. **单文件失败不影响整体**——解析错误记进 ``skipped_errors``（带行号），扫描继续；
4. 跳过明显的噪音目录（``.git`` / ``node_modules`` / ``__pycache__`` …），
   既提速也避免把依赖目录误当成 skill 来源。
"""

from __future__ import annotations

import os

from sfx.core.service import parser as skill_parser
from sfx.infra import pathx

#: 扫描时直接跳过的目录名（噪音 + 性能）
SKIP_DIRS = frozenset({
    ".git", ".hg", ".svn", "node_modules", "__pycache__", ".venv", "venv",
    ".idea", ".vscode", ".mypy_cache", ".pytest_cache", ".tox", "dist", "build",
    ".cache", ".gradle", ".next", ".terraform",
})

#: SKILL.md 的固定入口文件名
ENTRY_NAME = "SKILL.md"


def iter_skill_dirs(root: str, max_depth: int = 6) -> list[str]:
    """递归查找 ``root`` 下所有含 ``SKILL.md`` 的目录。

    Args:
        root: 来源根目录（绝对路径）。
        max_depth: 最大下钻层数，防止在巨型目录树里走太久。

    Returns:
        SKILL.md 的**绝对路径**列表（升序，保证扫描结果确定）。
    """
    if max_depth < 0:
        return []
    found: list[str] = []
    stack: list[tuple[str, int]] = [(root, 0)]
    while stack:
        current, depth = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError:
            continue  # 不可读目录静默跳过（权限不足不该中断扫描）
        for entry in entries:
            try:
                if entry.name == ENTRY_NAME and entry.is_file():
                    found.append(os.path.normpath(entry.path))
                    continue
                if not entry.is_dir():
                    continue
                if entry.name in SKIP_DIRS or entry.name.startswith("."):
                    continue
                if depth + 1 < max_depth:
                    stack.append((entry.path, depth + 1))
            except OSError:
                continue
    found.sort()
    return found


def _decide_action(repo, skill) -> str:
    """不写库地判断一次扫描对某技能会做什么（与 ``SkillRepo.upsert`` 同口径）。

    Returns:
        ``"add"`` / ``"update"`` / ``"unchanged"``。
    """
    existing = repo.find_key(skill.source_root, skill.dir_path)
    if existing is None:
        return "add"
    _, old_hash = existing
    if old_hash and old_hash == skill.content_hash:
        return "unchanged"
    return "update"


def scan(
    roots: tuple[str, ...],
    repo,
    logger,
    now_text: str,
    max_depth: int = 6,
    dry_run: bool = False,
) -> dict[str, object]:
    """扫描全部来源根并增量入库。

    Args:
        roots: 来源根列表（可含 ``~`` 或相对路径，内部统一展开）。
        repo: :class:`~sfx.infra.sqlite.skill_repo.SkillRepo`（或任何同构对象）。
        logger: 日志器（``infra.logx.Logger`` 或 ``NullLogger``）。
        now_text: RFC3339 UTC 时间戳（D-5）。
        max_depth: 单根最大下钻层数。
        dry_run: ``True`` 时只比对 ``content_hash`` 决定 action，**不写库**
            （不调用 ``repo.upsert``、不修复空主键）。

    Returns:
        统计字典，字段与 ARCH §5.2 的 ``sfx scan`` 契约一致：
        ``scanned_dirs`` / ``added`` / ``updated`` / ``unchanged`` /
        ``skipped_errors`` / ``skills_total``，外加 ``roots_missing``（附加信息）。
        ``dry_run=True`` 时额外返回 ``preview``（每技能 ``{slug, action}``，
        action ∈ ``add|update|unchanged``）。
    """
    added = 0
    updated = 0
    unchanged = 0
    scanned_dirs = 0
    skipped_errors: list[dict[str, object]] = []
    roots_missing: list[str] = []
    seen_entries: set[str] = set()
    preview: list[dict[str, object]] = []

    # 顺手修复历史遗留的空主键（见 SkillRepo.repair_ids 的说明）。
    # 失败不影响扫描主流程：修不了只是那几行继续隐形，不能让整次 scan 变红。
    # dry-run 绝不写库，故跳过修复（它是一条 UPDATE）。
    repaired_ids = 0
    if not dry_run:
        repair = getattr(repo, "repair_ids", None)
        if callable(repair):
            try:
                repaired_ids = int(repair() or 0)
            except Exception as exc:  # noqa: BLE001
                logger.warn("scanner", "repair_ids_failed", reason=type(exc).__name__)

    for raw_root in roots:
        root = pathx.expand(raw_root)
        if not os.path.isdir(root):
            # 目录不存在 = 用户没装这个工具，属正常情况，不报错
            roots_missing.append(raw_root)
            logger.info("scanner", "root_missing", root=raw_root)
            continue

        for entry_path in iter_skill_dirs(root, max_depth):
            key = pathx.norm_key(entry_path)
            if key in seen_entries:
                continue  # 多个来源根指向同一物理目录时只处理一次
            seen_entries.add(key)
            scanned_dirs += 1
            try:
                skill, warnings = skill_parser.parse_skill_file(entry_path, root, now_text)
            except skill_parser.ParseError as exc:
                # FR-02：报出行号并跳过该文件，整体扫描继续
                skipped_errors.append(
                    {"path": entry_path, "line": exc.line_no, "reason": exc.reason}
                )
                logger.warn(
                    "scanner", "skip_skill",
                    path=entry_path, line=exc.line_no, reason=exc.reason,
                )
                continue
            for item in warnings:
                logger.warn(
                    "scanner", "frontmatter_degraded",
                    path=item.get("path", ""), key=item.get("key", ""),
                    reason=item.get("reason", ""),
                )
            if dry_run:
                action = _decide_action(repo, skill)
                preview.append({"slug": skill.slug, "action": action})
                if action == "add":
                    added += 1
                elif action == "update":
                    updated += 1
                else:
                    unchanged += 1
                continue

            try:
                outcome = repo.upsert(skill)
            except Exception as exc:  # noqa: BLE001 - 单条写库失败不得中断扫描
                skipped_errors.append(
                    {"path": entry_path, "line": 0, "reason": f"写入失败：{exc}"}
                )
                logger.warn("scanner", "upsert_failed", path=entry_path)
                continue
            if outcome == "added":
                added += 1
            elif outcome == "updated":
                updated += 1
            else:
                unchanged += 1

    if not dry_run:
        repo.commit()
    return {
        "scanned_dirs": scanned_dirs,
        "added": added,
        "updated": updated,
        "unchanged": unchanged,
        "skipped_errors": skipped_errors,
        "roots_missing": roots_missing,
        "repaired_ids": repaired_ids,
        "skills_total": repo.count(),
        "preview": preview,
        "dry_run": dry_run,
    }
