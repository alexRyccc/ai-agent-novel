"""日志：文件轮转 + 永不污染 stdout（ARCH §10.3 / NFR-07）。

三条硬规则
----------
1. **永不写 stdout**：stdout 恒为一行 JSON（NN-2）。``--verbose`` 时额外写 stderr。
2. **按大小轮转**：单文件 5MB，保留 5 份（``sfx.log`` + ``.1`` ~ ``.4``），
   自实现轮转，不依赖外部 logrotate（保证内网离线可用）。
3. **隐私**：禁止记录任务正文、SKILL.md 正文、口令（§10.3）。调用方只能传
   哈希与长度；本模块也不提供任何"整段文本"级别的便捷方法，从 API 层面收敛。

格式：``2026-10-29T19:35:22Z|INFO|matcher|msg=... session=... elapsed_ms=...``
（管道分隔、UTC RFC3339、关键 ID 以 key=value 追加）。
"""

from __future__ import annotations

import os
import sys
import threading
import time

MAX_BYTES = 5 * 1024 * 1024  # 5MB
BACKUP_COUNT = 5             # sfx.log + sfx.log.1 ~ sfx.log.4

_LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
_ORDER = ("DEBUG", "INFO", "WARN", "ERROR")


def _utc_now() -> str:
    """UTC RFC3339（秒级），与 ``_boot.now_rfc3339`` 同格式。"""
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


class Logger:
    """极简文件日志器。

    Args:
        path: 日志文件路径；父目录不存在时自动创建。
        level: 最低记录级别，``DEBUG`` / ``INFO`` / ``WARN`` / ``ERROR``。
        verbose: 为 True 时**同时**写一份到 stderr（仍然绝不写 stdout）。
    """

    __slots__ = ("_path", "_level", "_verbose", "_lock")

    def __init__(self, path: str, level: str = "INFO", verbose: bool = False) -> None:
        self._path = path
        self._level = _LEVELS.get(level.upper(), 20)
        self._verbose = verbose
        self._lock = threading.Lock()
        parent = os.path.dirname(path)
        if parent:
            try:
                os.makedirs(parent, exist_ok=True)
            except OSError:
                pass

    # ---------------- 公开 API ----------------
    def debug(self, module: str, msg: str, **kv: object) -> None:
        """调试级（仅 ``--verbose`` 打开阈值时落盘）。"""
        self._log("DEBUG", module, msg, kv)

    def info(self, module: str, msg: str, **kv: object) -> None:
        """关键动作。"""
        self._log("INFO", module, msg, kv)

    def warn(self, module: str, msg: str, **kv: object) -> None:
        """已降级但功能仍可用。"""
        self._log("WARN", module, msg, kv)

    def error(self, module: str, msg: str, **kv: object) -> None:
        """需要人工介入。"""
        self._log("ERROR", module, msg, kv)

    def exception(self, module: str, msg: str, exc: BaseException) -> None:
        """记录异常堆栈。**只进日志文件**，绝不进 stdout（NFR-07 E-3）。"""
        import traceback  # 延迟导入：traceback 只在异常路径需要

        text = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        # 堆栈是排障的唯一依据，不能像普通字段那样截断到 512 字符
        self._log(
            "ERROR", module, msg,
            {"exc": type(exc).__name__, "stack": _safe(text, 20000)},
        )

    # ---------------- 内部实现 ----------------
    def _log(self, level: str, module: str, msg: str, kv: dict[str, object]) -> None:
        if _LEVELS[level] < self._level:
            return
        parts = [_utc_now(), level, module, f"msg={msg}"]
        for key, value in kv.items():
            parts.append(f"{key}={_safe(value)}")
        line = "|".join(parts) + "\n"

        with self._lock:
            try:
                self._rotate_if_needed()
                with open(self._path, "a", encoding="utf-8") as handle:
                    handle.write(line)
                    handle.flush()
            except OSError:
                pass  # 日志写失败绝不能影响主流程（E-4 精神）
            if self._verbose:
                try:
                    sys.stderr.write(line)
                    sys.stderr.flush()
                except (OSError, ValueError):
                    pass

    def _rotate_if_needed(self) -> None:
        """超过 5MB 就轮转，保留 5 份。"""
        try:
            if not os.path.exists(self._path):
                return
            if os.path.getsize(self._path) < MAX_BYTES:
                return
        except OSError:
            return

        # 先删最老的一份，再依次后移
        oldest = f"{self._path}.{BACKUP_COUNT - 1}"
        try:
            if os.path.exists(oldest):
                os.remove(oldest)
        except OSError:
            pass
        for index in range(BACKUP_COUNT - 2, 0, -1):
            src = f"{self._path}.{index}"
            dst = f"{self._path}.{index + 1}"
            try:
                if os.path.exists(src):
                    os.replace(src, dst)
            except OSError:
                pass
        try:
            os.replace(self._path, f"{self._path}.1")
        except OSError:
            pass


def _safe(value: object, limit: int = 512) -> str:
    """把任意值转成单行、日志安全的字符串（换行压成空格，避免伪造日志行）。

    Args:
        value: 任意值。
        limit: 长度上限。堆栈等排障关键内容可传入更大的上限。
    """
    text = str(value).replace("\r", " ").replace("\n", " ")
    if len(text) > limit:
        text = text[:limit] + "…(truncated)"
    return text


class NullLogger:
    """空日志器：尚未确定 home 时（例如只跑 ``--help``）使用的占位实现。"""

    __slots__ = ()

    def debug(self, module: str, msg: str, **kv: object) -> None:
        """空实现。"""

    def info(self, module: str, msg: str, **kv: object) -> None:
        """空实现。"""

    def warn(self, module: str, msg: str, **kv: object) -> None:
        """空实现。"""

    def error(self, module: str, msg: str, **kv: object) -> None:
        """空实现。"""

    def exception(self, module: str, msg: str, exc: BaseException) -> None:
        """空实现。"""
