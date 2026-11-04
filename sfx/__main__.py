"""``sfx`` 进程入口（ARCH §3.2 / NFR-07）。

四条在本文件里落地的铁律
------------------------
1. **必须有 ``__name__`` 守卫**（zipapp 坑 2，ARCH §2.3.2）
   zipapp 会在入口之外**再执行一次** ``__main__``；若在模块末尾裸写 ``main()``，
   stdout 就会出现**两行 JSON**，直接违反 NN-2「stdout 恒为一行 JSON」。
   所以这里只能写 ``if __name__ == "__main__": sys.exit(main())``。

2. **启动首行强制 UTF-8**（P-3）
   干净 Windows 上 ``sys.stdout.encoding == 'gbk'``，中文会输出成 GBK 字节，
   宿主按 UTF-8 解析必然乱码。**不修这一条，整份 JSON 契约在中文 Windows 上是假的。**

3. **3s 看门狗 + 顶层兜底**（E-2 / E-3）
   任何异常下 stdout 仍是**恰好一行合法 JSON**；堆栈**只进日志文件**，绝不进 stdout。
   退出码语义：``0`` 成功（含空结果）/ ``2`` 用法错 / ``4`` 内部错误（**可安全忽略继续**）/ ``5`` 需人工介入。

4. **只在成功路径输出一次**
   ``_emit_once`` 用模块级旗标保证"一生只写一行"，避免兜底路径与正常路径重复输出。
"""

from __future__ import annotations

import json
import os
import sys

from sfx import _boot

#: 一生只写一次 stdout 的守卫旗标（正常路径 / 兜底路径 / 看门狗 三选一先到先得）
_EMITTED = False

#: 兜底信封（连 Envelope 都构造不出来时的最后一道防线）
_FALLBACK_LINE = (
    '{"schema":"sfx.v1","ok":false,"code":"E_INTERNAL","data":null,'
    '"error":{"code":"E_INTERNAL","message":"内部错误：无法构造信封",'
    '"details":{},"hint":"详情见日志文件；可安全忽略并继续原任务"},'
    '"warnings":[],"elapsed_ms":0,"engine_version":"rule+dict+v1"}'
)


def _emit_once(line: str) -> None:
    """把**一行** JSON 写到 stdout，并保证整个进程只写一次。"""
    global _EMITTED
    if _EMITTED:
        return
    _EMITTED = True
    try:
        sys.stdout.write(line)
        sys.stdout.flush()
    except (OSError, ValueError, BrokenPipeError):
        # stdout 被关闭（例如宿主提前断开管道）：此时已无力回天，静默退出
        pass


def _dump(envelope, pretty: bool = False) -> str:
    """把信封序列化成 JSON。

    ``ensure_ascii=False`` 是必须的：否则中文会变成 ``\\uXXXX``，
    虽然合法但宿主侧（与人工排查）可读性极差。

    ``pretty=True`` 时输出缩进多行——**只有用户主动加 ``--human`` 才会发生**，
    且缩进 JSON 仍是合法 JSON，自动化调用方永远拿到一行（NN-2）。
    """
    try:
        if pretty:
            return json.dumps(envelope.to_dict(), ensure_ascii=False, indent=2)
        return json.dumps(envelope.to_dict(), ensure_ascii=False)
    except (TypeError, ValueError):
        return _FALLBACK_LINE


def _resolve_timeout_ms(opts: dict[str, object]) -> int:
    """解析看门狗超时：``--timeout`` > ``$SFX_TIMEOUT_MS`` > 3000ms。"""
    from sfx.cli import dispatch

    value = dispatch.opt_int(opts, "timeout")
    if value is not None and value > 0:
        return value
    env_value = os.environ.get("SFX_TIMEOUT_MS", "")
    try:
        parsed = int(float(env_value))
    except ValueError:
        parsed = 0
    return parsed if parsed > 0 else 3000


def main() -> None:
    """进程入口。**不返回**，直接以 ``sys.exit(code)`` 结束。

    为什么不让 ``main()`` 返回退出码
    --------------------------------
    zipapp 生成的根 ``__main__.py`` 内容实测是::

        # -*- coding: utf-8 -*-
        import sfx.__main__
        sfx.__main__.main()

    也就是**返回值被丢弃**。如果 ``main()`` 只是 ``return 2``，
    zipapp 形态下退出码恒为 0 —— ``E_USAGE`` 的 2、``E_INTERNAL`` 的 4 全部失效，
    宿主永远以为"执行成功"（本机实测复现：源码形态 exit=2，zipapp 形态 exit=0）。
    因此 ``main()`` 必须自己调用 ``sys.exit``，让退出码在两种形态下都正确。

    真正的逻辑在 :func:`_run`，它只负责**算出**退出码。
    """
    sys.exit(_run())


def _run() -> int:
    """执行主流程并**返回**退出码（0 / 2 / 4 / 5）。

    本函数不向外抛异常：所有异常都在内部转成信封。
    """
    # ① 必须最先执行：修好 stdout/stderr 编码（P-3）
    _boot.force_utf8()

    # 以下导入放在函数内：让 force_utf8 尽可能早地跑完，
    # 且导入顺序不影响"第一行输出一定是 UTF-8"这件事。
    from sfx import _errors as errors
    from sfx import _watchdog
    from sfx.cli import dispatch
    from sfx.core.model.envelope import Envelope
    from sfx.infra import logx, pathx

    argv = sys.argv[1:]
    _, _, opts = dispatch.scan_argv(argv)
    verbose = dispatch.opt_bool(opts, "verbose")

    # ② 尽早确定 home，使后续任何异常都有日志文件可写
    home = pathx.resolve_home(dispatch.opt_str(opts, "home"))
    logger = logx.Logger(pathx.log_path(home), "INFO", verbose)

    timeout_ms = _resolve_timeout_ms(opts)

    def _emit(envelope, pretty: bool = False) -> None:
        _emit_once(_dump(envelope, pretty) + "\n")

    def _on_signal(signum: int) -> None:
        """收到中断信号：仍输出一行 JSON，绝不留下"半个输出"。"""
        logger.warn("main", "signal_received", signum=signum)
        _emit(
            Envelope.failure(
                errors.SfxError(
                    errors.E_INTERNAL,
                    f"被信号中断（signum={signum}）",
                    {"signum": signum},
                    "可安全忽略并继续原任务",
                ),
                elapsed_ms=_boot.elapsed_ms(),
            )
        )
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        _watchdog.hard_exit(4)

    def _on_timeout() -> None:
        """看门狗到点：输出降级信封后立即硬退出（E-2：绝不阻塞 Metis）。"""
        logger.error("main", "watchdog_timeout", timeout_ms=timeout_ms)
        _emit(
            Envelope.failure(
                errors.SfxError(
                    errors.E_TIMEOUT,
                    f"执行超过 {timeout_ms}ms 已终止",
                    {"timeout_ms": timeout_ms},
                    "可安全忽略并继续原任务；或加大 --timeout 重试",
                ),
                elapsed_ms=_boot.elapsed_ms(),
            )
        )
        try:
            sys.stdout.flush()
        except (OSError, ValueError):
            pass
        _watchdog.hard_exit(4)

    def _panic_hook(etype, value, traceback) -> None:
        """``sys.excepthook`` 兜底：E-3 要求 panic 不外泄，堆栈只进日志。"""
        if issubclass(etype, SystemExit):
            return
        try:
            logger.exception("main", "panic", value)
        except Exception:  # noqa: BLE001
            pass
        _emit(Envelope.failure(value, elapsed_ms=_boot.elapsed_ms()))
        _watchdog.hard_exit(errors.exit_code_for(errors.E_INTERNAL))

    sys.excepthook = _panic_hook
    _watchdog.install_signal_handlers(_on_signal)

    # 长驻服务（serve）不启动看门狗：看门狗用于"绝不让 Metis 等超过 3s"，
    # 而 serve 是用户主动开启的本地看板，没有"卡住宿主"这回事，反而会被
    # 3s 定时器误杀（实测：serve 启动后 3s 即 E_TIMEOUT 硬退出）。
    command_name = dispatch.scan_argv(argv)[0]
    watchdog = None
    if command_name != "serve":
        watchdog = _watchdog.Watchdog(timeout_ms, _on_timeout)
        watchdog.start()

    try:
        envelope = dispatch.run(argv)
        if envelope is None:
            # --help / --version 已自行输出（§5.2 的豁免情形）
            if watchdog is not None:
                watchdog.cancel()
            return 0
        _emit(envelope, pretty=dispatch.requests_pretty(argv))
        if watchdog is not None:
            watchdog.cancel()
        return envelope.exit_code
    except errors.SfxError as err:
        # 业务错误：错误码已冻结，直接转信封
        logger.warn("main", "sfx_error", code=err.code, message=err.message)
        _emit(Envelope.failure(err, elapsed_ms=_boot.elapsed_ms()))
        if watchdog is not None:
            watchdog.cancel()
        return err.exit_code
    except BaseException as exc:  # noqa: BLE001 - E-3：兜底未知错误
        logger.exception("main", "panic", exc)
        _emit(Envelope.failure(exc, elapsed_ms=_boot.elapsed_ms()))
        if watchdog is not None:
            watchdog.cancel()
        return errors.exit_code_for(errors.E_INTERNAL)


if __name__ == "__main__":
    # zipapp 会在入口之外再执行一次本模块，因此**必须**有 __name__ 守卫，
    # 否则 main() 被调用两次 → stdout 出现两行 JSON（ARCH §2.3.2 坑 2）。
    # main() 内部已调用 sys.exit，这里加一层 sys.exit 仅为源码形态下语义完整。
    main()
