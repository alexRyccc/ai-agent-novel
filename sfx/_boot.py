"""启动最小集：计时起点、stdout/stderr 强制 UTF-8、平台探测。

为什么必须独立成模块
--------------------
ARCH §2.4 **P-3**：实测干净 Windows 环境下 ``sys.stdout.encoding == 'gbk'``、
``sys.flags.utf8_mode == 0``，此时 ``json.dumps(..., ensure_ascii=False)`` 的中文
（如 ``内部规范``）会被编码成 GBK 字节 ``b'\\xc4\\xda\\xb2\\xbf\\xb9\\xe6\\xb7\\xb6'``，
宿主按 UTF-8 解析必然乱码或报错。也就是说：**不先修好 stdout 编码，
"stdout 恒为一行合法 JSON"这条契约（NN-2）在中文 Windows 上就是假的。**

因此 ``force_utf8()`` 必须是 ``main()`` 的第一行动作，且本模块只能 import
``sys`` / ``time`` / ``os`` 这些零成本模块（``time`` 与 ``os`` 是解释器启动即加载的
内置/引导模块，实测增量 ≈ 0ms）。
"""

from __future__ import annotations

import sys
import time

#: 进程启动计时起点（单调时钟，不受系统时间回拨影响）
T0: float = time.perf_counter()

#: 平台探测结果，避免在热路径反复调用 sys.platform / os.name
IS_WINDOWS: bool = sys.platform.startswith("win")


def force_utf8() -> None:
    """把 stdout / stderr / stdin 强制重配置为 UTF-8 + ``\\n`` 换行。

    - ``encoding="utf-8"``：保证中文、emoji 等都能正确编码（P-3）。
    - ``newline="\\n"``：禁止 Windows 把 ``\\n`` 翻译成 ``\\r\\n``。
      一行 JSON 里混入 ``\\r`` 会让部分 JSON 解析器与 diff 工具行为不一致。

    任何一步失败都静默跳过：编码再糟也比启动崩溃强，真正的兜底在 ``__main__`` 的
    ``try/except`` 里（NFR-07 E-3）。
    """
    for name in ("stdout", "stderr", "stdin"):
        stream = getattr(sys, name, None)
        if stream is None:
            continue
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:  # 已被重定向为自定义对象
            continue
        try:
            reconfigure(encoding="utf-8", newline="\n")
        except (ValueError, OSError, AttributeError):
            # 例如交互式环境下 stdin 不允许改 newline；忽略即可
            pass


def elapsed_ms() -> int:
    """返回自进程启动以来的毫秒数（整数，写入信封的 ``elapsed_ms``）。"""
    return int((time.perf_counter() - T0) * 1000)


def now_rfc3339() -> str:
    """返回当前 UTC 时间的 RFC3339 字符串（ARCH §10.5）。

    时间一律由应用层生成，**绝不使用 SQL 的 ``datetime('now')``**（跨库纪律 D-5）。
    格式示例：``2026-10-29T11:35:22Z``（秒级，日志与入库精度足够）。
    """
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
