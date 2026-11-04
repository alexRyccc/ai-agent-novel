"""错误码表 + 统一异常（ARCH §10.2）。

错误码表是**冻结项**：只能新增，不能改名或改语义。
本模块保持零依赖（不 import json），因为它被 ``__main__`` 与所有命令共享，
且必须在任何情况下都能被导入成功。
"""

from __future__ import annotations

# --------------------------------------------------------------------------
# 错误码（ARCH §10.2「错误码表（冻结）」）
# --------------------------------------------------------------------------
OK = "OK"
EMPTY_MATCH = "EMPTY_MATCH"

E_USAGE = "E_USAGE"
E_CONFIG = "E_CONFIG"
E_STORE = "E_STORE"
E_LOCK = "E_LOCK"
E_TIMEOUT = "E_TIMEOUT"
E_FILE_IO = "E_FILE_IO"
E_ANCHOR_CORRUPT = "E_ANCHOR_CORRUPT"
E_CONV_TRACKED_BY_GIT = "E_CONV_TRACKED_BY_GIT"
E_VERSION_NEWER = "E_VERSION_NEWER"
E_MISSING_VAR = "E_MISSING_VAR"
E_NOT_FOUND = "E_NOT_FOUND"
E_PERMISSION = "E_PERMISSION"
E_AUTH = "E_AUTH"
E_VALIDATE = "E_VALIDATE"
E_INTERNAL = "E_INTERNAL"

#: 错误码 → CLI 退出码（ARCH §10.2「退出码语义」）
#:   0 成功（含空结果） / 2 用法错 / 4 内部错误（Metis 可安全忽略继续） / 5 需人工介入
EXIT_BY_CODE: dict[str, int] = {
    OK: 0,
    EMPTY_MATCH: 0,
    E_USAGE: 2,
    E_CONFIG: 4,
    E_STORE: 4,
    E_LOCK: 4,
    E_TIMEOUT: 4,
    E_FILE_IO: 4,
    E_ANCHOR_CORRUPT: 4,
    E_CONV_TRACKED_BY_GIT: 4,
    E_VERSION_NEWER: 4,
    E_MISSING_VAR: 4,
    E_NOT_FOUND: 4,
    E_VALIDATE: 4,
    E_INTERNAL: 4,
    E_PERMISSION: 5,
    E_AUTH: 5,
}

#: 未知/未登记错误码的兜底退出码
DEFAULT_EXIT = 4


def exit_code_for(code: str) -> int:
    """把错误码映射为进程退出码；未知码一律按"内部错误"处理（4）。"""
    return EXIT_BY_CODE.get(code, DEFAULT_EXIT)


class SfxError(Exception):
    """业务异常：携带冻结错误码，最终会被转成统一信封。

    Attributes:
        code: 冻结错误码，见本模块常量。
        message: 面向人类（与宿主）的一句话说明，**不含堆栈、不含正文**。
        details: 结构化补充信息（如 ``{"path": ..., "line": 42}``）。
        hint: 可执行的下一步建议（如 ``执行 sfx scan 重建索引``）。
    """

    __slots__ = ("code", "message", "details", "hint")

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
        hint: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.details = details if details is not None else {}
        self.hint = hint

    def error_object(self) -> dict[str, object]:
        """构造信封里的 ``error`` 对象（ARCH §5.1）。"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "hint": self.hint,
        }

    @property
    def exit_code(self) -> int:
        """该错误对应的进程退出码。"""
        return exit_code_for(self.code)
