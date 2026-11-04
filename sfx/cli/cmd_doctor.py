"""``sfx doctor``：环境与数据目录自检（ARCH §5.2）。

输出 ``data`` 与契约一致：``home`` / ``db_path`` / ``db_size`` / ``migrations`` /
``skills`` / ``events`` / ``last_scan_at`` / ``uninstall_hint``。

排障价值
--------
``sfx doctor`` 是用户（以及安装脚本）确认"数据到底落在哪"的唯一权威来源。
Windows 上数据目录是 ``%LOCALAPPDATA%\\sfx``，很多人会去找 ``~/.sfx``——
所以 ``home`` 与 ``db_path`` 必须是**绝对路径原文打印**。

注意：本命令**不会创建数据库**（只在库已存在时读取），
避免"查个信息就顺手建了个库"这种副作用。
"""

from __future__ import annotations

import os
import sys

from sfx import _boot
from sfx.cli import dispatch
from sfx.core.model.envelope import Envelope

ALLOWED_FLAGS: frozenset[str] = frozenset({"json", "human"})


def run(cfg, logger, opts: dict[str, object], positional: list[str]) -> Envelope:
    """执行自检。

    Args:
        cfg: :class:`~sfx.infra.conf.Config`。
        logger: 日志器。
        opts: 选项字典。
        positional: 位置参数（不使用）。

    Returns:
        :class:`Envelope`。
    """
    dispatch.reject_unknown(opts, ALLOWED_FLAGS, "doctor")

    from sfx.infra import pathx
    from sfx.infra.sqlite import event_repo, migrator, skill_repo
    from sfx.infra.sqlite import open as sqlite_open

    home = cfg.home
    db_path = pathx.db_path(home)
    db_exists = os.path.isfile(db_path)
    db_size = os.path.getsize(db_path) if db_exists else 0

    migrations: list[int] = []
    skills = 0
    events = 0
    sessions = 0
    last_scan_at = ""

    if db_exists:
        conn = sqlite_open.open_db(db_path)
        try:
            migrations = migrator.applied_versions(conn)
            skills = skill_repo.SkillRepo(conn).count()
            event_repository = event_repo.EventRepo(conn)
            events = event_repository.count_events()
            sessions = event_repository.count_sessions()
            last_scan_at = skill_repo.SkillRepo(conn).last_scanned_at()
        finally:
            sqlite_open.close_db(conn)

    data: dict[str, object] = {
        "home": home,
        "db_path": db_path,
        "db_exists": db_exists,
        "db_size": db_size,
        "db_size_human": _human_size(db_size),
        "config_path": cfg.config_path,
        "migrations": migrations,
        "latest_migration": migrator.LATEST_VERSION,
        "skills": skills,
        "events": events,
        "sessions": sessions,
        "last_scan_at": last_scan_at,
        "log_path": pathx.log_path(home),
        "cache_dir": pathx.cache_dir(home),
        "roots": [pathx.expand(root) for root in cfg.roots],
        "threshold": cfg.threshold,
        "top_n": cfg.top_n,
        "semantic": cfg.semantic,
        "weights": dict(cfg.weights),
        "python": sys.version.split()[0],
        "platform": sys.platform,
        "uninstall_hint": (
            f"完全卸载 = 删除数据目录 {home}"
            "（Windows 另需删除 sfx.cmd 与其 PATH 条目）；"
            "不残留注册表、不残留服务"
        ),
    }
    return Envelope.success(data=data, elapsed_ms=_boot.elapsed_ms())


def _human_size(size: int) -> str:
    """把字节数转成人类可读形式（不引第三方、不用 locale）。"""
    units = ("B", "KB", "MB", "GB")
    value = float(size)
    index = 0
    while value >= 1024.0 and index < len(units) - 1:
        value /= 1024.0
        index += 1
    if index == 0:
        return f"{int(value)} {units[index]}"
    return f"{value:.1f} {units[index]}"
