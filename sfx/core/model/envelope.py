"""统一信封（ARCH §5.1）——CLI 与 HTTP 共用同一 Schema。

冻结字段（只能增、不能改语义）：``schema`` / ``ok`` / ``data`` / ``error`` /
``elapsed_ms`` / ``engine_version``。

本实现**新增**两个字段（§5.1 明确"冻结后只增字段"）：
- ``code``：顶层结果码。必要性来自 ``EMPTY_MATCH``——它 ``ok=true`` 但需要一个
  区别于 ``OK`` 的标识；若塞进 ``error`` 就与"``ok=true`` 时 ``error=null``"矛盾。
- ``warnings``：降级说明数组（NFR-07 E-4 要求"写库失败时附一条降级说明"）。
"""

from __future__ import annotations

from sfx import ENVELOPE_SCHEMA, ENGINE_VERSION
from sfx import _errors as errors


class Envelope:
    """一次 CLI 调用的唯一输出结构。"""

    __slots__ = ("ok", "code", "data", "error", "warnings", "elapsed_ms", "engine_version")

    def __init__(
        self,
        ok: bool = True,
        code: str = errors.OK,
        data: dict[str, object] | None = None,
        error: dict[str, object] | None = None,
        warnings: list[str] | None = None,
        elapsed_ms: int = 0,
        engine_version: str = ENGINE_VERSION,
    ) -> None:
        self.ok = ok
        self.code = code
        self.data = data
        self.error = error
        self.warnings = warnings if warnings is not None else []
        self.elapsed_ms = elapsed_ms
        self.engine_version = engine_version

    # ---------------- 构造糖 ----------------
    @classmethod
    def success(
        cls,
        data: dict[str, object] | None = None,
        code: str = errors.OK,
        warnings: list[str] | None = None,
        elapsed_ms: int = 0,
        engine_version: str = ENGINE_VERSION,
    ) -> "Envelope":
        """成功（``ok=true``，``error=null``）。"""
        return cls(
            ok=True, code=code, data=data, error=None,
            warnings=warnings, elapsed_ms=elapsed_ms, engine_version=engine_version,
        )

    @classmethod
    def failure(
        cls,
        err: errors.SfxError | BaseException,
        elapsed_ms: int = 0,
        engine_version: str = ENGINE_VERSION,
    ) -> "Envelope":
        """失败。``SfxError`` 用其冻结错误码；其它异常一律 ``E_INTERNAL``（不泄漏细节）。"""
        if isinstance(err, errors.SfxError):
            error_obj = err.error_object()
            code = err.code
        else:
            error_obj = {
                "code": errors.E_INTERNAL,
                "message": f"内部错误：{type(err).__name__}",
                "details": {},
                "hint": "详情见日志文件；该错误可安全忽略并继续原任务",
            }
            code = errors.E_INTERNAL
        return cls(
            ok=False, code=code, data=None, error=error_obj,
            warnings=[], elapsed_ms=elapsed_ms, engine_version=engine_version,
        )

    # ---------------- 输出 ----------------
    def to_dict(self) -> dict[str, object]:
        """转成 JSON 可序列化的字典（键顺序固定，便于 golden 断言）。"""
        return {
            "schema": ENVELOPE_SCHEMA,
            "ok": self.ok,
            "code": self.code,
            "data": self.data,
            "error": self.error,
            "warnings": self.warnings,
            "elapsed_ms": self.elapsed_ms,
            "engine_version": self.engine_version,
        }

    @property
    def exit_code(self) -> int:
        """对应的进程退出码（0 成功 / 2 用法错 / 4 内部错误 / 5 需人工介入）。"""
        return errors.exit_code_for(self.code)
