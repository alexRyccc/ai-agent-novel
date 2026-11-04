"""跨平台目录与路径规范（ARCH §10.1）。

平台布局
--------
====================  ==========================================
用途                  路径
====================  ==========================================
Home（DB/日志/缓存根） Windows ``%LOCALAPPDATA%\\sfx``（回退 ``%APPDATA%\\sfx``）
                      Linux 桌面 ``$XDG_DATA_HOME/sfx`` 或 ``~/.local/share/sfx``
                      Linux 服务端 ``/var/lib/sfx``
配置文件              ``<home>/config.yaml``（Linux 服务端优先 ``/etc/sfx/config.yaml``）
数据库                ``<home>/sfx.db``（文件名不可改，保证单库可拷贝迁移，NFR-06）
日志                  ``<home>/logs/sfx.log``（5×5MB 轮转）
匹配索引缓存          ``<home>/cache/``
====================  ==========================================

两条极易踩的纪律
----------------
1. **所有文件 IO 必须显式 ``encoding="utf-8"``**，绝不依赖 locale 默认编码
   （中文 Windows 上是 GBK，见 P-3）。
2. **UNC / 网络共享盘必须可用**（Q10=B）：因此禁用任何"以 ``/`` 开头才算绝对路径"
   的平台假设，一律用 ``os.path`` 处理；对外输出用**操作系统原生分隔符**，
   方便 Metis 直接拿路径去 Read（§10.1 规则 3 / NN-4）。

本模块只 import ``os`` / ``sys``（解释器启动即加载，实测增量 ≈ 0）。
"""

from __future__ import annotations

import os
import sys

APP_NAME = "sfx"
DB_NAME = "sfx.db"
LOG_NAME = "sfx.log"
CONFIG_NAME = "config.yaml"

IS_WINDOWS = sys.platform.startswith("win")


def _is_server_context() -> bool:
    """Linux 下判断是否"服务端"语境（root + 存在 /var/lib）。

    这是一个启发式判定：ARCH §10.1 把 Linux 分成"桌面（XDG）"与"服务端（/var/lib）"
    两种布局，但没有可靠的环境变量可区分。root 且存在 ``/var/lib`` 时按服务端处理，
    其余一律按桌面处理。**任何情况下都可用 ``SFX_HOME`` / ``--home`` 覆盖**。
    """
    if IS_WINDOWS:
        return False
    geteuid = getattr(os, "geteuid", None)
    if geteuid is None:
        return False
    try:
        return geteuid() == 0 and os.path.isdir("/var/lib")
    except OSError:
        return False


def default_home() -> str:
    """返回平台默认的数据根目录（不含命令行/环境变量覆盖）。"""
    if IS_WINDOWS:
        base = os.environ.get("LOCALAPPDATA") or os.environ.get("APPDATA")
        if base:
            return os.path.join(base, APP_NAME)
        return os.path.join(os.path.expanduser("~"), "." + APP_NAME)
    if _is_server_context():
        return os.path.join("/var", "lib", APP_NAME)
    xdg = os.environ.get("XDG_DATA_HOME")
    if xdg:
        return os.path.join(xdg, APP_NAME)
    return os.path.join(os.path.expanduser("~"), ".local", "share", APP_NAME)


def resolve_home(cli_home: str | None = None) -> str:
    """解析数据根目录，优先级：``--home`` > ``$SFX_HOME`` > 平台默认。

    注意：配置文件**不参与** home 的解析（配置文件本身就在 home 下，存在循环依赖）。
    """
    if cli_home:
        return expand(cli_home)
    env_home = os.environ.get("SFX_HOME")
    if env_home:
        return expand(env_home)
    return default_home()


def default_config_path(home: str) -> str:
    """返回默认配置文件路径（Linux 服务端优先 ``/etc/sfx/config.yaml``）。"""
    if not IS_WINDOWS and _is_server_context():
        etc_path = os.path.join("/etc", APP_NAME, CONFIG_NAME)
        if os.path.isfile(etc_path):
            return etc_path
    return os.path.join(home, CONFIG_NAME)


def resolve_config_path(cli_config: str | None, home: str) -> str:
    """解析配置文件路径：``--config`` > ``$SFX_CONFIG`` > 平台默认。"""
    if cli_config:
        return expand(cli_config)
    env_cfg = os.environ.get("SFX_CONFIG")
    if env_cfg:
        return expand(env_cfg)
    return default_config_path(home)


def expand(path: str) -> str:
    """展开 ``~`` 与环境变量，并归一化为**绝对路径**（不使用 ``os.path.realpath``）。

    为什么不用 ``realpath``：它会解析符号链接与 ``..``，在网络共享盘 / UNC 上可能
    返回与用户预期不同的路径，破坏"入库路径 == 用户看到的路径"这条直觉（§10.1 规则 3）。
    只用 ``abspath`` + ``normpath``，语义可预测。
    """
    return os.path.normpath(os.path.abspath(os.path.expandvars(os.path.expanduser(path))))


def norm_key(path: str) -> str:
    """唯一性判定用的归一化键。

    DB 用 ``(source_root, dir_path)`` 唯一约束防重复扫描（FR-01）。
    在大小写不敏感的平台（Windows）上统一 lower，避免同一目录被记成两条。
    """
    return os.path.normcase(expand(path))


def native(path: str) -> str:
    """输出给宿主（JSON / 路由卡）时使用的路径形式：操作系统原生分隔符。

    Windows 用 ``\\``、POSIX 用 ``/``——``os.path.normpath`` 已经保证这一点，
    这里保留为独立函数是为了让"对外路径形态"这件事有唯一出处。
    """
    return os.path.normpath(path)


def db_path(home: str) -> str:
    """数据库文件路径（文件名固定为 ``sfx.db``，不可配置）。"""
    return os.path.join(home, DB_NAME)


def log_dir(home: str) -> str:
    """日志目录。"""
    return os.path.join(home, "logs")


def log_path(home: str) -> str:
    """当前日志文件路径。"""
    return os.path.join(log_dir(home), LOG_NAME)


def cache_dir(home: str) -> str:
    """匹配索引 / 词典缓存目录。"""
    return os.path.join(home, "cache")


def ensure_dir(path: str) -> None:
    """确保目录存在（幂等）。失败时静默：调用方会在真正写文件时报错。"""
    try:
        os.makedirs(path, exist_ok=True)
    except OSError:
        pass


def ensure_parent(path: str) -> None:
    """确保文件的父目录存在。"""
    parent = os.path.dirname(path)
    if parent:
        ensure_dir(parent)


