"""3 秒硬看门狗 + 跨平台优雅退出（ARCH §2.4 P-4 / NFR-07 E-2）。

为什么不能用信号实现超时
------------------------
ARCH §2.4 **P-4** 实测：**Windows 没有 ``signal.SIGALRM``**（``signal.SIGALRM``
直接不存在），Go 版常用的 ``time.AfterFunc`` 语义在 Python 侧只能靠线程实现。
故本模块用 ``threading.Timer``：到点后**不抛异常**（异常在非主线程里没人接），
而是直接输出降级信封并 ``os._exit(4)``——这是唯一能保证"一定在 3s 内吐出一行 JSON"
的做法（NFR-07 E-2：绝不阻塞 Metis）。

为什么用 ``os._exit`` 而不是 ``sys.exit``
----------------------------------------
``sys.exit`` 抛 ``SystemExit``，会触发 ``finally`` / ``atexit`` / 线程 join，
这些清理动作可能再次阻塞（例如 SQLite 持锁）。``os._exit`` 跳过所有清理，
代价是不 flush 缓冲区——所以调用方**必须**先 ``flush()``。
"""

from __future__ import annotations

import os
import signal
import threading

DEFAULT_TIMEOUT_MS = 3000


class Watchdog:
    """一次性硬超时定时器。

    Args:
        timeout_ms: 超时毫秒数，<=0 表示禁用看门狗。
        on_timeout: 超时回调。**必须**自行输出一行 JSON 并结束进程
            （实现里走 ``os._exit``）；回调内不要再抛异常。
    """

    __slots__ = ("_timeout_s", "_on_timeout", "_timer", "_fired")

    def __init__(self, timeout_ms: int, on_timeout) -> None:
        self._timeout_s = timeout_ms / 1000.0 if timeout_ms and timeout_ms > 0 else 0.0
        self._on_timeout = on_timeout
        self._timer: threading.Timer | None = None
        self._fired = False

    @property
    def fired(self) -> bool:
        """看门狗是否已经触发（供日志与自检使用）。"""
        return self._fired

    def start(self) -> None:
        """启动定时器。``timeout_ms <= 0`` 时不启动（便于排查时临时关闭）。"""
        if self._timeout_s <= 0:
            return

        def _fire() -> None:
            self._fired = True
            self._on_timeout()

        timer = threading.Timer(self._timeout_s, _fire)
        timer.daemon = True  # 主进程正常退出时不得被它拖住
        timer.start()
        self._timer = timer

    def cancel(self) -> None:
        """主流程正常结束时取消定时器，避免"跑完还被杀"的误伤。"""
        if self._timer is not None:
            self._timer.cancel()
            self._timer = None


def install_signal_handlers(on_signal) -> None:
    """注册跨平台优雅退出处理器。

    Windows 的终端中断是 ``CTRL_BREAK_EVENT``（对应 ``signal.SIGBREAK``），
    只处理 ``SIGTERM`` 在 Windows 上等于没处理（P-4）。这里按"存在即注册"的方式
    覆盖 Windows / POSIX 两套：
      - ``SIGINT``  / ``SIGTERM``：两者都有
      - ``SIGBREAK``：仅 Windows 有

    Args:
        on_signal: 收到信号时的回调（签名 ``(signum) -> None``）。
    """
    wanted = ["SIGINT", "SIGTERM", "SIGBREAK"]
    for name in wanted:
        sig = getattr(signal, name, None)
        if sig is None:
            continue  # 该平台无此信号（如 POSIX 无 SIGBREAK）
        try:
            signal.signal(sig, lambda signum, _frame, _cb=on_signal: _cb(signum))
        except (ValueError, OSError):
            # 非主线程注册会抛 ValueError；此时保持默认行为即可
            pass


def hard_exit(code: int) -> None:
    """立即结束进程，跳过所有清理（仅供看门狗超时路径使用）。"""
    os._exit(code)
