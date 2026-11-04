"""``sfx scan``：扫描来源目录并增量入库（ARCH §5.2）。

输出 ``data`` 字段与契约一致：
``scanned_dirs`` / ``added`` / ``updated`` / ``unchanged`` / ``skipped_errors[]`` /
``skills_total``（外加附加信息 ``roots_missing``）。

本命令是**非热路径**，所以在这里顺手预热同义词缓存——
让随后的 ``sfx match`` 不必付 ``importlib.resources`` 的 +205ms（见 ``matcher`` 文档）。
"""

from __future__ import annotations

from sfx import _boot
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope

ALLOWED_FLAGS: frozenset[str] = frozenset(
    {"roots", "full", "json", "human", "dry-run", "diff"}
)


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """执行扫描。

    Args:
        cfg: :class:`~sfx.infra.conf.Config`。
        logger: 日志器。
        opts: 选项字典。
        positional: 位置参数（``scan`` 不使用）。

    Returns:
        :class:`Envelope`。
    """
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "scan")

    # 命令内延迟导入：让 `sfx --help` 与未命中命令的路径不付这些导入成本
    from sfx.core.service import matcher, scanner
    from sfx.infra import pathx
    from sfx.infra.sqlite import migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    dry_run = dispatch.opt_bool(opts, "dry-run")
    diff = dispatch.opt_bool(opts, "diff")

    now_text = _boot.now_rfc3339()
    home = cfg.home
    db_path = pathx.db_path(home)
    pathx.ensure_dir(home)

    conn = sqlite_open.open_db(db_path)
    try:
        applied = migrator.migrate(conn, now_text)
        if applied:
            logger.info("scan", "migrated", versions=applied)
        repo = skill_repo.SkillRepo(conn)
        stats = scanner.scan(
            cfg.roots, repo, logger, now_text, cfg.scan_max_depth,
            dry_run=(dry_run or diff),
        )
    finally:
        sqlite_open.close_db(conn)

    # 预热同义词缓存（失败无所谓，match 会自行降级）
    matcher.warm_synonym_cache(home, logger)

    data: dict[str, object] = dict(stats)
    data["roots"] = [str(root) for root in cfg.roots]
    data["home"] = home
    data["db_path"] = db_path
    data["full"] = dispatch.opt_bool(opts, "full")

    # ``--diff`` 等价于 dry-run，但只列出有变化的（add/update，不含 unchanged）
    if diff:
        data["preview"] = [
            item for item in data["preview"]
            if item.get("action") in ("add", "update")
        ]

    logger.info(
        "scan", "finished",
        scanned_dirs=stats["scanned_dirs"], added=stats["added"],
        updated=stats["updated"], unchanged=stats["unchanged"],
        skipped=len(stats["skipped_errors"]),
    )
    return Envelope.success(data=data, elapsed_ms=_boot.elapsed_ms())
