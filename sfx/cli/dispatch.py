"""手写 argv 扫描与命令分派（ARCH §3.2 / §2.1）。

为什么不用 ``argparse``
----------------------
实测 ``import argparse`` 增量 **+77.7ms**（ARCH §2.1 记为 +54.6ms，本机更差），
而 ``sfx match`` 是**每次任务都要跑**的热路径，冷启动预算只有 300ms（NFR-05）。
手写 argv 扫描只有几十行，省下的却是预算里最大的一块之一。

（非热路径命令也统一走这里：一条解析路径 = 一套行为，避免"两种 CLI 语义"。）

本模块顶层**只允许 import ``sys``**：``sfx --help`` 必须尽可能快，
``pathx`` / ``conf`` / ``sqlite3`` 等一律在 :func:`run` 内按需导入。
"""

from __future__ import annotations

import sys

from sfx import ENGINE_VERSION, __version__

#: 命令 → (模块名, 入口函数名)。延迟导入，避免一次加载全部命令的依赖。
COMMANDS: dict[str, tuple[str, str]] = {
    "scan": ("sfx.cli.cmd_scan", "run"),
    "load": ("sfx.cli.cmd_load", "run"),
    "match": ("sfx.cli.cmd_match", "run"),
    "prime": ("sfx.cli.cmd_prime", "run"),
    "sync": ("sfx.cli.cmd_sync", "run"),
    "serve": ("sfx.cli.cmd_serve", "run"),
    "doctor": ("sfx.cli.cmd_doctor", "run"),
}

#: 全局 flag（所有命令共用，由 dispatch 消费，不下传给命令）
GLOBAL_FLAGS: frozenset[str] = frozenset({
    "home", "config", "timeout", "verbose", "help", "version",
})

HELP_TEXT = """sfx —— SkillForge 命令行（Walking Skeleton 版本）

用法:
  sfx <command> [options]

命令:
  scan                     扫描来源目录并把 skill 增量入库
  match --task "<描述>"     按任务描述匹配 skill，返回路由卡（不含正文）
  prime --task "<描述>"     匹配后生成一段可直接粘贴给 Metis 的自包含指令块
  sync                     生成/更新约定文件（agent.md），让 Metis 自动调 skill
  load <slug>              上报一次"采纳"（闭合准确率漏斗，采纳率才有分子）
  serve                    启动本地 Web 看板（默认 http://127.0.0.1:7788）
  doctor                   打印数据目录 / 数据库 / 迁移 / 统计信息

全局选项:
  --home <path>            覆盖数据根目录（> $SFX_HOME > 平台默认）
  --config <path>          覆盖配置文件路径
  --timeout <ms>           看门狗超时（默认 3000ms）
  --verbose                日志同时输出到 stderr（stdout 恒为一行 JSON）
  --help, -h               显示本帮助
  --version                显示版本

stdout 恒为恰好一行 JSON（ARCH NN-2）。任何失败都不应阻塞调用方继续任务。
"""

SHORT_FLAGS = {"h": "help", "v": "version"}


def scan_argv(argv: list[str]) -> tuple[str, list[str], dict[str, object]]:
    """把 argv 拆成 ``(命令, 位置参数, 选项字典)``。

    支持三种写法：``--key value``、``--key=value``、``--flag``（布尔）。
    ``--`` 之后的内容一律按位置参数处理。
    """
    positional: list[str] = []
    opts: dict[str, object] = {}
    index = 0
    total = len(argv)
    while index < total:
        token = argv[index]
        if token == "--":
            positional.extend(argv[index + 1 :])
            break
        if token.startswith("--"):
            body = token[2:]
            if "=" in body:
                name, value = body.split("=", 1)
                opts[name] = value
            else:
                nxt = argv[index + 1] if index + 1 < total else None
                if nxt is not None and not nxt.startswith("-"):
                    opts[body] = nxt
                    index += 1
                else:
                    opts[body] = True
        elif token.startswith("-") and len(token) > 1:
            for ch in token[1:]:
                opts[SHORT_FLAGS.get(ch, ch)] = True
        else:
            positional.append(token)
        index += 1
    command = positional[0] if positional else ""
    return command, positional[1:], opts


def opt_str(opts: dict[str, object], name: str) -> str | None:
    """取字符串选项；缺省或布尔 True 时返回 ``None``。"""
    value = opts.get(name)
    if isinstance(value, str):
        return value
    return None


def opt_int(opts: dict[str, object], name: str) -> int | None:
    """取整数选项；解析失败返回 ``None``。"""
    value = opts.get(name)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return int(float(str(value)))
    except ValueError:
        return None


def opt_bool(opts: dict[str, object], name: str) -> bool:
    """取布尔选项（存在且非 ``False`` 即视为 True）。"""
    value = opts.get(name)
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in ("", "0", "false", "no")


def reject_unknown(opts: dict[str, object], allowed: frozenset[str], command: str) -> None:
    """拒绝该命令不认识的 flag。

    Raises:
        SfxError: ``E_USAGE`` —— 列出不认识的 flag，帮助宿主/用户修正命令。
    """
    from sfx import _errors as errors

    unknown = sorted(set(opts) - allowed - GLOBAL_FLAGS)
    if unknown:
        raise errors.SfxError(
            errors.E_USAGE,
            f"sfx {command} 不支持选项：{', '.join('--' + name for name in unknown)}",
            {"command": command, "unknown": unknown},
            f"执行 sfx {command} --help 查看可用选项",
        )


def _print_help() -> None:
    """打印帮助（**唯一**允许多行输出到 stdout 的情形之一，ARCH §5.2 例外条款）。"""
    sys.stdout.write(HELP_TEXT)


def _print_version() -> None:
    """打印版本信息（单行，非 JSON，属 §5.2 明确豁免的元命令）。"""
    sys.stdout.write(f"sfx {__version__} engine={ENGINE_VERSION}\n")


def run(argv: list[str]) -> object | None:
    """解析 argv 并执行对应命令。

    Returns:
        :class:`~sfx.core.model.envelope.Envelope`，或 ``None``
        （表示已经打印了 help / version，调用方无需再输出信封）。

    Raises:
        SfxError: 用法错误或配置错误（由 ``__main__`` 转成信封）。
    """
    command, positional, opts = scan_argv(argv)

    # 顺序很重要：``sfx --version`` 没有命令名，若先判"空命令→help"就会把
    # --version 吞掉（实测踩到过）。故先处理两个显式元 flag，再兜底空命令。
    if opt_bool(opts, "help") or command == "help":
        _print_help()
        return None
    if opt_bool(opts, "version"):
        _print_version()
        return None
    if command == "":
        _print_help()
        return None

    if command not in COMMANDS:
        from sfx import _errors as errors

        raise errors.SfxError(
            errors.E_USAGE,
            f"未知命令：{command or '(空)'}",
            {"command": command, "known": sorted(COMMANDS)},
            "可用命令：" + ", ".join(sorted(COMMANDS)),
        )

    # ---- 以下为真正需要 IO 的路径，全部延迟导入 ----
    from sfx import _errors as errors
    from sfx.infra import conf, logx, pathx

    module_name, func_name = COMMANDS[command]
    try:
        module = __import__(module_name, fromlist=[func_name])
    except ImportError as exc:
        raise errors.SfxError(
            errors.E_INTERNAL,
            f"命令模块加载失败：{module_name}",
            {"module": module_name},
            "该 sfx.pyz 可能不完整，请重新获取",
        ) from exc
    handler = getattr(module, func_name)

    home = pathx.resolve_home(opt_str(opts, "home"))
    config_path = pathx.resolve_config_path(opt_str(opts, "config"), home)
    verbose = opt_bool(opts, "verbose")

    flags: dict[str, object] = {}
    timeout = opt_int(opts, "timeout")
    if timeout is not None:
        flags["timeout_ms"] = timeout
    roots = opt_str(opts, "roots")
    if roots:
        flags["roots"] = roots

    cfg = conf.load(home, config_path, flags)
    logger = logx.Logger(
        pathx.log_path(home), level="DEBUG" if verbose else "INFO", verbose=verbose
    )
    return handler(cfg, logger, opts, positional)


def requests_pretty(argv: list[str]) -> bool:
    """命令行是否要求"人类可读"的多行输出（``--human``）。

    说明：``--human`` 输出的是 **indent=2 的 JSON**，仍然是合法 JSON，
    只是不再是"一行"。这是 ARCH §5.2 里 ``--help`` 那类豁免的同类处理：
    只有用户**主动**加了这个 flag 才会发生，自动化调用方永远拿到一行。
    """
    _, _, opts = scan_argv(argv)
    return opt_bool(opts, "human")
