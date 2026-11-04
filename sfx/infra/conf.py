"""配置加载与优先级解析（ARCH §10.1「配置优先级」）。

优先级：**命令行 flag > ``SFX_*`` 环境变量 > 配置文件 > 内置默认**。

配置文件本身是 YAML，而我们**没有 YAML 库**——直接用 ``sfx._frontmatter`` 的
YAML 子集解析器（它就是为此场景顺带可用的），零新增依赖。

环境变量清单
------------
``SFX_HOME`` / ``SFX_CONFIG`` / ``SFX_ROOTS``（逗号分隔）/ ``SFX_THRESHOLD`` /
``SFX_TOP_N`` / ``SFX_TIMEOUT_MS`` / ``SFX_SEMANTIC`` /
``SFX_WEIGHT_KEYWORD`` / ``SFX_WEIGHT_TAG`` / ``SFX_WEIGHT_SEMANTIC`` /
``SFX_WEIGHT_HISTORY``
"""

from __future__ import annotations

import os

from sfx import _errors as errors

DEFAULT_ROOTS: tuple[str, ...] = (
    "~/.workbuddy/skills",
    "~/.claude/skills",
    ".cursor/rules",
)
DEFAULT_THRESHOLD = 0.22
DEFAULT_TOP_N = 3
DEFAULT_SEMANTIC = "off"          # WS-2 不做 BM25（§12.6.2），正式版默认 bm25
DEFAULT_WEIGHTS: dict[str, float] = {
    "keyword": 0.40,
    "tag": 0.20,
    "semantic": 0.25,
    "history": 0.15,
}
DEFAULT_TIMEOUT_MS = 3000
DEFAULT_SCAN_MAX_DEPTH = 6

#: 参与加权求和的信号名（顺序固定，保证归一化结果确定）
SIGNAL_NAMES: tuple[str, ...] = ("keyword", "tag", "semantic", "history")


class Config:
    """运行时配置（不可变语义：加载后只读）。"""

    __slots__ = (
        "roots", "threshold", "top_n", "semantic", "weights",
        "timeout_ms", "scan_max_depth", "home", "config_path", "sources",
    )

    def __init__(
        self,
        roots: tuple[str, ...] = DEFAULT_ROOTS,
        threshold: float = DEFAULT_THRESHOLD,
        top_n: int = DEFAULT_TOP_N,
        semantic: str = DEFAULT_SEMANTIC,
        weights: dict[str, float] | None = None,
        timeout_ms: int = DEFAULT_TIMEOUT_MS,
        scan_max_depth: int = DEFAULT_SCAN_MAX_DEPTH,
        home: str = "",
        config_path: str = "",
        sources: dict[str, str] | None = None,
    ) -> None:
        self.roots = roots
        self.threshold = threshold
        self.top_n = top_n
        self.semantic = semantic
        self.weights = dict(weights) if weights else dict(DEFAULT_WEIGHTS)
        self.timeout_ms = timeout_ms
        self.scan_max_depth = scan_max_depth
        self.home = home
        self.config_path = config_path
        self.sources = sources or {}

    # ------------------------------------------------------------------
    def weight(self, name: str) -> float:
        """取某个信号的权重（缺失按 0 处理）。"""
        return float(self.weights.get(name, 0.0))

    def active_signals(self) -> tuple[str, ...]:
        """返回权重 > 0 的信号名（``history`` 可被配置为 0 —— ARCH §12.6.2.1 C-1）。"""
        return tuple(name for name in SIGNAL_NAMES if self.weight(name) > 0)

    def to_dict(self) -> dict[str, object]:
        """导出为可 JSON 序列化的字典（供 ``sfx doctor`` 展示）。"""
        return {
            "roots": list(self.roots),
            "threshold": self.threshold,
            "top_n": self.top_n,
            "semantic": self.semantic,
            "weights": dict(self.weights),
            "timeout_ms": self.timeout_ms,
            "scan_max_depth": self.scan_max_depth,
            "home": self.home,
            "config_path": self.config_path,
        }


def _as_float(value: object, default: float) -> float:
    """宽松转 float，失败返回默认值（配置文件手改错时不该让 CLI 崩）。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def _as_int(value: object, default: int) -> int:
    """宽松转 int，失败返回默认值。"""
    try:
        return int(float(str(value).strip()))
    except (TypeError, ValueError):
        return default


def _as_str_tuple(value: object) -> tuple[str, ...]:
    """把配置里的列表/逗号分隔字符串统一成字符串元组。"""
    if isinstance(value, (list, tuple)):
        return tuple(str(item).strip() for item in value if str(item).strip())
    text = str(value).strip()
    if not text:
        return ()
    return tuple(part.strip() for part in text.split(",") if part.strip())


def load_file(path: str) -> dict[str, object]:
    """读取并解析配置文件；文件不存在时返回空字典（用默认值即可）。

    Raises:
        SfxError: ``E_CONFIG`` —— 配置文件存在但 YAML 结构不可恢复（带行号）。
    """
    if not path or not os.path.isfile(path):
        return {}
    # 延迟导入：``_frontmatter`` 是本项目最大的纯 Python 模块（约 700 行），
    # 只有在**确实存在配置文件**时才付它的解析/编译成本。
    # 没有配置文件的机器（绝大多数）在 ``sfx match`` 热路径上零开销。
    from sfx import _frontmatter as fm

    try:
        with open(path, "r", encoding="utf-8") as handle:
            text = handle.read()
    except OSError as exc:
        raise errors.SfxError(
            errors.E_CONFIG,
            f"配置文件无法读取：{path}",
            {"path": path, "errno": exc.errno},
            "检查文件权限，或用 --config 指定另一个路径",
        ) from exc
    try:
        return fm.parse_mapping(text)
    except fm.FrontMatterError as exc:
        raise errors.SfxError(
            errors.E_CONFIG,
            f"配置文件 YAML 语法错误（第 {exc.line_no} 行）：{exc.message}",
            {"path": path, "line": exc.line_no},
            "修正该行后重试；或直接删除该文件以使用内置默认配置",
        ) from exc


def _pick(
    key: str,
    flags: dict[str, object],
    env_name: str,
    file_data: dict[str, object],
    default: object,
    sources: dict[str, str],
) -> object:
    """按 flag > env > file > default 取值，并记录来源（``sfx config get`` 要回显）。"""
    if key in flags and flags[key] is not None:
        sources[key] = "flag"
        return flags[key]
    env_value = os.environ.get(env_name)
    if env_value not in (None, ""):
        sources[key] = "env"
        return env_value
    if key in file_data:
        sources[key] = "file"
        return file_data[key]
    sources[key] = "default"
    return default


def load(home: str, config_path: str, flags: dict[str, object] | None = None) -> Config:
    """组装完整配置。

    Args:
        home: 已解析的数据根目录（由 ``pathx.resolve_home`` 得到）。
        config_path: 已解析的配置文件路径。
        flags: 命令行 flag 字典（键名见本模块各 ``_pick`` 调用）。

    Raises:
        SfxError: ``E_CONFIG`` —— 配置文件非法。
    """
    flags = flags or {}
    sources: dict[str, str] = {}
    file_data = load_file(config_path)

    # 配置文件支持 engine.weights.xxx 的嵌套写法（这里同时兼容扁平写法）
    engine = file_data.get("engine")
    engine_data: dict[str, object] = engine if isinstance(engine, dict) else {}
    nested_weights = engine_data.get("weights")
    weights_data: dict[str, object] = (
        nested_weights if isinstance(nested_weights, dict) else {}
    )
    flat_weights = file_data.get("weights")
    if isinstance(flat_weights, dict):
        merged = dict(flat_weights)
        merged.update(weights_data)
        weights_data = merged

    roots_value = _pick("roots", flags, "SFX_ROOTS", file_data, DEFAULT_ROOTS, sources)
    threshold_value = _pick(
        "threshold", flags, "SFX_THRESHOLD", engine_data, DEFAULT_THRESHOLD, sources
    )
    top_n_value = _pick("top_n", flags, "SFX_TOP_N", engine_data, DEFAULT_TOP_N, sources)
    semantic_value = _pick(
        "semantic", flags, "SFX_SEMANTIC", engine_data, DEFAULT_SEMANTIC, sources
    )
    timeout_value = _pick(
        "timeout_ms", flags, "SFX_TIMEOUT_MS", file_data, DEFAULT_TIMEOUT_MS, sources
    )
    depth_value = _pick(
        "scan_max_depth", flags, "SFX_SCAN_MAX_DEPTH", file_data,
        DEFAULT_SCAN_MAX_DEPTH, sources,
    )

    weights: dict[str, float] = {}
    for name in SIGNAL_NAMES:
        # 配置文件里的键就是信号名本身（engine.weights.history），
        # 环境变量是 SFX_WEIGHT_<NAME>，命令行 flag 也是信号名。
        raw = _pick(
            name,
            flags,
            f"SFX_WEIGHT_{name.upper()}",
            weights_data,
            DEFAULT_WEIGHTS[name],
            sources,
        )
        weights[name] = max(0.0, _as_float(raw, DEFAULT_WEIGHTS[name]))

    return Config(
        roots=_as_str_tuple(roots_value),
        threshold=_as_float(threshold_value, DEFAULT_THRESHOLD),
        top_n=_as_int(top_n_value, DEFAULT_TOP_N),
        semantic=str(semantic_value).strip() or DEFAULT_SEMANTIC,
        weights=weights,
        timeout_ms=_as_int(timeout_value, DEFAULT_TIMEOUT_MS),
        scan_max_depth=_as_int(depth_value, DEFAULT_SCAN_MAX_DEPTH),
        home=home,
        config_path=config_path,
        sources=sources,
    )
