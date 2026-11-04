"""错误码 / 警告码 / 信封出口（ARCH §5.1.1 **单一权威源** · §10.2 · §10.2.1）。

为什么这个文件必须存在且唯一
----------------------------
§5.1.1 明确："本文档中**只有这一张表**定义错误码/警告码的含义与退出码；
§10.2、§12.2、§12.9 等章节**只引用，不再重新定义**。"
对应到代码，就是：**所有 `E_*` / `W_*` 字面量只能出现在本文件**，业务代码一律引用常量。

出口唯一化（E-1 的落地方式）
----------------------------
§10.2 纪律："全项目只有 `_errors.emit()` 能写 stdout"。
因此本文件提供 :func:`emit` 作为**唯一**的 stdout 写入点，并用模块级旗标保证
"一个进程只写一次"——正常路径 / 兜底路径 / 看门狗三者先到先得，
绝不会出现两行 JSON（ARCH §2.3.2 坑二）。

零依赖：本模块不在顶层 import 任何模块（`json`/`os` 都在函数内延迟导入），
因此它可以被最早启动的 ``_boot`` 与任何兜底路径安全地导入。
"""

from __future__ import annotations

# ==========================================================================
# 一、结果码（ok=true 时使用）
# ==========================================================================
OK = "OK"
EMPTY_MATCH = "EMPTY_MATCH"          # 成功但无命中：matched=[]，ok 仍为 true

# ==========================================================================
# 二、错误码 E_*（出现在 error.code，ok=false）—— 逐条对应 §5.1.1（1）
# ==========================================================================
E_USAGE = "E_USAGE"
E_CONFIG = "E_CONFIG"
E_STORE = "E_STORE"
E_LOCK = "E_LOCK"
E_TIMEOUT = "E_TIMEOUT"
E_FILE_IO = "E_FILE_IO"
E_ANCHOR_CORRUPT = "E_ANCHOR_CORRUPT"
E_VERSION_NEWER = "E_VERSION_NEWER"
E_MISSING_VAR = "E_MISSING_VAR"
E_NOT_FOUND = "E_NOT_FOUND"
E_PERMISSION = "E_PERMISSION"
E_AUTH = "E_AUTH"
E_VALIDATE = "E_VALIDATE"
E_INTERNAL = "E_INTERNAL"

# 🆕 §5.1.1 新增（未冻结）
E_PY_RUNTIME = "E_PY_RUNTIME"                        # Python 版本 <3.11（R-22）
E_CONV_TRACKED_BY_GIT = "E_CONV_TRACKED_BY_GIT"      # FR-48：约定文件已被 Git 跟踪
E_SHARE_LEAK = "E_SHARE_LEAK"                        # FR-47：共享变体自检命中 S1~S4

# ==========================================================================
# 三、警告码 W_*（出现在 warnings[].code，不阻断主返回）—— 逐条对应 §5.1.1（2）
# ==========================================================================
W_GIT_EXCLUDE_FAILED = "W_GIT_EXCLUDE_FAILED"
W_GITIGNORE_MODIFIED = "W_GITIGNORE_MODIFIED"
W_CONV_TRACKED_BY_GIT = "W_CONV_TRACKED_BY_GIT"      # 🔴 CRITICAL
W_CONV_IN_HISTORY = "W_CONV_IN_HISTORY"              # 🔴 CRITICAL
W_INDEX_COMPACTED = "W_INDEX_COMPACTED"
W_INDEX_BUDGET = "W_INDEX_BUDGET"
W_TRUNCATED = "W_TRUNCATED"

#: ⚠ 以下两个码**尚未登记进 §5.1.1**，但是 §10.2 E-4 明确要求的产物：
#:   "写库失败只记 warn 日志，信封数据照常返回并在 warnings[] 里附降级说明"。
#: 代码必须有码才能承载，故先实现，并已请求架构师补进登记表（未冻结，可改名）。
W_TELEMETRY_FAILED = "W_TELEMETRY_FAILED"            # 埋点写库失败（E-4）
W_SYNONYMS_UNAVAILABLE = "W_SYNONYMS_UNAVAILABLE"    # 同义词词典不可用（§7.2.3 降级链）

#: 本文件是唯一权威源：这两个元组供 ``sfx doctor`` 自检与单测断言使用
ERROR_CODES: tuple[str, ...] = (
    OK, EMPTY_MATCH,
    E_USAGE, E_CONFIG, E_STORE, E_LOCK, E_TIMEOUT, E_FILE_IO,
    E_ANCHOR_CORRUPT, E_VERSION_NEWER, E_MISSING_VAR, E_NOT_FOUND,
    E_PERMISSION, E_AUTH, E_VALIDATE, E_INTERNAL,
    E_PY_RUNTIME, E_CONV_TRACKED_BY_GIT, E_SHARE_LEAK,
)
WARNING_CODES: tuple[str, ...] = (
    W_GIT_EXCLUDE_FAILED, W_GITIGNORE_MODIFIED,
    W_CONV_TRACKED_BY_GIT, W_CONV_IN_HISTORY,
    W_INDEX_COMPACTED, W_INDEX_BUDGET, W_TRUNCATED,
    W_TELEMETRY_FAILED, W_SYNONYMS_UNAVAILABLE,
)

# ==========================================================================
# 四、退出码映射（§5.1.2）
# ==========================================================================
#: 错误码 → 退出码。0 成功（含空结果）/ 2 用法错 / 4 内部或环境错误 / 5 需人工介入
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
    E_VERSION_NEWER: 4,
    E_MISSING_VAR: 4,
    E_NOT_FOUND: 4,
    E_VALIDATE: 4,
    E_INTERNAL: 4,
    E_PY_RUNTIME: 4,
    E_CONV_TRACKED_BY_GIT: 4,
    E_SHARE_LEAK: 4,
    E_PERMISSION: 5,
    E_AUTH: 5,
}

#: 未登记错误码的兜底退出码（内部错误，宿主可安全忽略）
DEFAULT_EXIT = 4

#: 单条响应允许的 warning 条数上限（§5.1：超出折叠为 1 条 W_TRUNCATED）
MAX_WARNINGS = 20


def exit_code_for(code: str) -> int:
    """把结果码/错误码映射为进程退出码；未登记的码按"内部错误"处理（4）。"""
    return EXIT_BY_CODE.get(code, DEFAULT_EXIT)


# ==========================================================================
# 五、异常与警告对象
# ==========================================================================
class SfxError(Exception):
    """业务异常：携带 §5.1.1 登记的错误码。

    Attributes:
        code: 冻结错误码常量之一（**禁止**业务代码硬编码字符串）。
        message: 一句话说明，**不含堆栈、不含正文**。
        details: 结构化补充信息（如 ``{"path": ..., "line": 42}``）。
        hint: 可执行的下一步建议。
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
        """构造信封里的 ``error`` 对象（`{code,message,details,hint}`）。"""
        return {
            "code": self.code,
            "message": self.message,
            "details": self.details,
            "hint": self.hint,
        }

    @property
    def exit_code(self) -> int:
        """该错误对应的进程退出码（§5.1.2）。"""
        return exit_code_for(self.code)


def warning(
    code: str,
    message: str,
    details: dict[str, object] | None = None,
    hint: str = "",
) -> dict[str, object]:
    """构造一条 warning（元素结构与 ``error`` **完全相同**，§5.1）。

    为什么用同一个结构：消费方可以复用同一个解析器，不必为 warnings 写第二套。
    """
    return {
        "code": code,
        "message": message,
        "details": details if details is not None else {},
        "hint": hint,
    }


def truncate_warnings(items: list[dict[str, object]]) -> list[dict[str, object]]:
    """把 warnings 折叠到 ``MAX_WARNINGS`` 条以内（超出 → 1 条 `W_TRUNCATED`）。

    §5.1：单条响应最多 20 条，超出折叠为 1 条 ``W_TRUNCATED``，避免刷屏。
    """
    if len(items) <= MAX_WARNINGS:
        return items
    return [
        warning(
            W_TRUNCATED,
            f"警告数量 {len(items)} 超过上限 {MAX_WARNINGS}，已折叠",
            {"total": len(items), "kept": MAX_WARNINGS},
            "详情见日志文件",
        )
    ]


# ==========================================================================
# 六、唯一的 stdout 出口
# ==========================================================================
#: 一个进程只写一次 stdout 的守卫旗标（正常路径 / 兜底路径 / 看门狗 先到先得）
_EMITTED = False

#: 连 Envelope 都构造不出来时的最后一道防线（保持"永远可解析"）
_FALLBACK_LINE = (
    '{"schema":"sfx.v1","ok":false,"code":"E_INTERNAL","data":null,'
    '"error":{"code":"E_INTERNAL","message":"无法构造信封",'
    '"details":{},"hint":"详情见日志文件；可安全忽略并继续原任务"},'
    '"warnings":[],"elapsed_ms":0,"engine_version":"rule+dict+v1"}'
)


def has_emitted() -> bool:
    """本进程是否已经写过 stdout（自检/单测用）。"""
    return _EMITTED


def emit(envelope: object, pretty: bool = False) -> None:
    """**唯一的 stdout 写入点**（§10.2「出口唯一化」）。

    - 序列化为**压缩的单行**（``separators=(",", ":")``），满足 E-1；
      ``ensure_ascii=False`` 让中文保持可读（前提是 §10.1.1 的 UTF-8 重配已生效）。
    - ``pretty=True`` 时输出 ``indent=2``：仅用户主动加 ``--human`` 才发生，
      且缩进 JSON 仍是合法 JSON。
    - warnings 超过 20 条在此折叠为 1 条 ``W_TRUNCATED``。
    - 若存在 warning，**额外**往 stderr 打一行人类可读摘要（§5.1「CLI 出口」）。

    本函数**永不抛异常**：stdout 被关闭、对象不可序列化等一律降级。
    """
    global _EMITTED
    if _EMITTED:
        return
    _EMITTED = True

    import json

    try:
        payload = envelope.to_dict() if hasattr(envelope, "to_dict") else envelope
    except Exception:  # noqa: BLE001 - 连 to_dict 都炸了
        payload = None

    if isinstance(payload, dict) and isinstance(payload.get("warnings"), list):
        payload = dict(payload)
        payload["warnings"] = truncate_warnings(payload["warnings"])
        warn_codes = [str(item.get("code", "")) for item in payload["warnings"]]
    else:
        warn_codes = []

    try:
        if isinstance(payload, (dict, list)):
            if pretty:
                line = json.dumps(payload, ensure_ascii=False, indent=2)
            else:
                line = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        else:
            line = _FALLBACK_LINE
    except (TypeError, ValueError):
        line = _FALLBACK_LINE

    try:
        import sys

        stream = sys.stdout
        stream.write(line + "\n")
        stream.flush()
    except (OSError, ValueError, AttributeError):
        pass  # stdout 被关闭（宿主提前断开管道）时无力回天，静默退出

    if warn_codes:
        _warn_to_stderr(warn_codes)


def _warn_to_stderr(codes: list[str]) -> None:
    """往 stderr 打一行 warning 摘要（**不影响** stdout 的那一行 JSON）。"""
    try:
        import sys

        sys.stderr.write(f"sfx: {len(codes)} warning(s): {'; '.join(codes)}\n")
        sys.stderr.flush()
    except (OSError, ValueError, AttributeError):
        pass


def emit_text(text: str) -> None:
    """写多行人类可读文本到 stdout —— **仅供 ``--help`` / ``--version``**（§5.2 豁免条款）。

    仍然走本模块，是为了让"全项目只有一个 stdout 写入点"这条断言可机器校验。
    """
    global _EMITTED
    if _EMITTED:
        return
    _EMITTED = True
    try:
        import sys

        sys.stdout.write(text)
        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        pass


def exit_with(envelope: object, code: int) -> None:
    """先 ``emit`` 再硬退出（看门狗 / 兜底 / 信号路径专用）。

    为什么用 ``os._exit`` 而不是 ``sys.exit``（§10.2.1 **T-2**）：
    ``sys.exit`` 抛的 ``SystemExit`` 继承自 ``BaseException``，
    会被顶层的 ``except BaseException`` 捕获，从而拖住 Metis（违反 NN-2）。
    """
    emit(envelope)
    try:
        import sys

        sys.stdout.flush()
    except (OSError, ValueError, AttributeError):
        pass
    import os

    os._exit(code)


def install_excepthook(on_exception) -> None:
    """安装 ``sys.excepthook`` 兜底（§10.2 ③-c）。

    Args:
        on_exception: 回调，签名 ``(etype, value, traceback) -> None``。
            实现里必须自行 ``emit`` 一行 JSON 并结束进程。
    """
    import sys

    def _hook(etype, value, traceback) -> None:
        # SystemExit 不是"崩溃"：交给解释器正常退出，避免二次输出
        if issubclass(etype, SystemExit):
            return
        on_exception(etype, value, traceback)

    sys.excepthook = _hook


def enable_faulthandler() -> None:
    """把致命错误（native 崩溃）的栈写到 **stderr**（§10.2 ③-d）。

    与 stdout 完全隔离，因此不违反 E-1。失败静默——这只是取证增强，不是契约。
    """
    try:
        import faulthandler
        import sys

        faulthandler.enable(file=sys.stderr)
    except Exception:  # noqa: BLE001
        pass
