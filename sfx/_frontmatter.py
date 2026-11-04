"""SKILL.md / config.yaml 的 YAML 子集解析 + 行级 patch 回写（ARCH §2.2）。

这是本项目**唯一**无法用 stdlib 直接替代的能力（stdlib 无 YAML），按 §2.2.4 的结论
采用"单引擎手写解析器"，**不引入 PyYAML**。

三条硬要求及其实现方案
----------------------
1. **语法子集**（§2.2.2）
   支持：顶层 ``key: value``（bool/int/float/字符串类型推断）、单双引号字符串、
   块列表 ``- item``、行内列表 ``[a, b]``、嵌套映射、``#`` 注释与空行。

   .. note:: 相对 ARCH §2.2.2 有一处**有意扩展**：文档限定"一层嵌套映射"，
      但 ``config.yaml`` 需要 ``engine.weights.keyword`` 两层。§2.2.4 明确写了
      "子集不够用时**扩展子集**"，故这里实现为任意深度的递归嵌套映射。
      对 SKILL.md front-matter 而言行为与一层版本完全一致（多出来的能力不影响既有输入）。

2. **降级策略**（§2.2.3，必须与 FR-02 对齐）
   - 合法但超出子集（块标量 ``|``/``>``、锚点 ``&``、别名 ``*``、流式映射 ``{a: b}``、
     显式标签 ``!!str``）→ **不抛异常**：原文整段进 ``raw_fields``，记 ``warnings``
     行号与原因，置 ``partial=True``，**继续入库**；
   - 结构不可恢复（缺 ``:``、缩进无法配对、顶层出现列表项、引号不闭合）
     → 抛 :class:`FrontMatterError`（带 1-based 行号），调用方按 FR-02 跳过该文件。

3. **双向一致性**（§2.2.5，比解析更难）
   核心：**行级 patch，绝不整体重新序列化**。
   本模块持有全文的 ``lines``（保留每一行的行尾换行符），恒有::

       "".join(fm.lines) == 原文

   于是"解析后不经任何修改直接 ``dump()``"必然**字节相等**（round-trip 恒等，
   也是 ``tests/test_frontmatter.py`` 的 golden 断言）。改字段时只替换
   ``key_lines[key]`` 覆盖的那几行，**引号风格、注释、字段顺序、缩进全部保留**。
"""

from __future__ import annotations

__all__ = [
    "FrontMatter",
    "FrontMatterError",
    "parse_document",
    "parse_mapping",
]

_TRUE = {"true", "yes", "on"}
_FALSE = {"false", "no", "off"}
_NULLISH = {"", "~", "null", "none"}
_FENCES = ("---", "...")


class FrontMatterError(Exception):
    """结构不可恢复的 YAML 语法错误（对应 FR-02：报行号 + 跳过该文件）。"""

    __slots__ = ("line_no", "message")

    def __init__(self, line_no: int, message: str) -> None:
        super().__init__(f"第 {line_no} 行：{message}")
        self.line_no = line_no
        self.message = message


class FrontMatter:
    """一份文档的解析产物。

    不用 ``@dataclass``：本模块被 ``infra.conf`` 引入 ``sfx match`` 热路径，
    而 ``dataclasses`` 实测 +38.6ms（详见 ``core/model/skill.py`` 的说明）。

    Attributes:
        lines: 全文按行拆分且**保留行尾**，``"".join(lines)`` 恒等于原文。
        fields: 解析出的字段（嵌套映射为嵌套 dict）。
        raw_fields: 超出子集的字段原文（键可能带 ``.`` 前缀表示嵌套路径）。
        key_lines: 每个 key 在 ``lines`` 中的 ``(起始下标, 结束下标)``（闭区间）。
        warnings: 降级记录，元素为 ``{"line": int, "key": str, "reason": str}``。
        partial: 是否存在"合法但超出子集"的字段（对应 ``frontmatter_partial`` 标记）。
        has_fm: 文档是否含 ``---`` front-matter 块。
        fm_start / fm_end: 围栏行在 ``lines`` 中的下标（无围栏时为 -1）。
        body_start: 正文起始下标（无围栏时为 0）。
    """

    __slots__ = (
        "lines", "fields", "raw_fields", "key_lines", "warnings",
        "partial", "has_fm", "fm_start", "fm_end", "body_start",
    )

    def __init__(
        self,
        lines: list[str],
        fields: dict[str, object] | None = None,
        raw_fields: dict[str, str] | None = None,
        key_lines: dict[str, tuple[int, int]] | None = None,
        warnings: list[dict[str, object]] | None = None,
        partial: bool = False,
        has_fm: bool = False,
        fm_start: int = -1,
        fm_end: int = -1,
        body_start: int = 0,
    ) -> None:
        self.lines = lines
        self.fields = fields if fields is not None else {}
        self.raw_fields = raw_fields if raw_fields is not None else {}
        self.key_lines = key_lines if key_lines is not None else {}
        self.warnings = warnings if warnings is not None else []
        self.partial = partial
        self.has_fm = has_fm
        self.fm_start = fm_start
        self.fm_end = fm_end
        self.body_start = body_start

    # ---------------- 读取 ----------------
    def body_text(self) -> str:
        """返回 Markdown 正文（front-matter 之后的部分）。"""
        return "".join(self.lines[self.body_start:])

    def dump(self) -> str:
        """导出全文。**未做任何修改时，返回值与原文字节完全相等**（§2.2.5 验收断言）。"""
        return "".join(self.lines)

    def get(self, key: str, default: object = None) -> object:
        """取字段值；缺省返回 ``default``。"""
        return self.fields.get(key, default)

    def has(self, key: str) -> bool:
        """字段是否存在（含值为空串的情况）。"""
        return key in self.fields

    # ---------------- 回写（行级 patch） ----------------
    def set_value(self, key: str, value: object) -> None:
        """把 ``key`` 改写为 ``value``，**只替换该 key 覆盖的那几行**。

        已存在的 key 沿用其原有的缩进与引号风格；不存在的 key 走 :meth:`append_field`。
        """
        if key in self.key_lines:
            start, end = self.key_lines[key]
            indent = _indent_of(self.lines[start])
            style = _value_style(self.lines[start])
            new_lines = _render_lines(indent, key.split(".")[-1], value, style)
            self.lines[start : end + 1] = new_lines
            self._shift(start + 1, len(new_lines) - (end - start + 1))
            self.key_lines[key] = (start, start + len(new_lines) - 1)
            self.fields[key] = value
            self.raw_fields.pop(key, None)
        else:
            self.append_field(key, value)

    def append_field(self, key: str, value: object) -> None:
        """在 front-matter 末尾追加新字段（缩进沿用现有风格）。

        若文档原本没有 front-matter，则在文首插入一对 ``---`` 围栏。
        """
        indent = _detect_indent(self)
        new_lines = _render_lines(indent, key, value, "plain")

        if not self.has_fm:
            self.lines[0:0] = ["---\n"] + new_lines + ["---\n"]
            self.has_fm = True
            self.fm_start = 0
            self.fm_end = len(new_lines) + 1
            self.body_start = self.fm_end + 1
            _register_new_key(self, key, 1, len(new_lines))
            self.fields[key] = value
            return

        insert_at = self.fm_end  # 插在结束围栏之前
        self.lines[insert_at:insert_at] = new_lines
        self._shift(insert_at, len(new_lines))
        self.fm_end += len(new_lines)
        self.body_start += len(new_lines)
        _register_new_key(self, key, insert_at, len(new_lines))
        self.fields[key] = value

    def _shift(self, from_idx: int, delta: int) -> None:
        """行下标平移后修正所有记录的行号（保证后续 patch 仍然打在正确的行上）。"""
        if delta == 0:
            return
        for name, (start, end) in list(self.key_lines.items()):
            if start >= from_idx:
                self.key_lines[name] = (start + delta, end + delta)
            elif end >= from_idx:
                self.key_lines[name] = (start, end + delta)


def _register_new_key(fm: FrontMatter, key: str, start: int, count: int) -> None:
    """把新写入的 key 登记进 ``key_lines``（供后续 patch 复用）。"""
    fm.key_lines[key] = (start, start + count - 1)


# ==========================================================================
# 文本切分与行工具
# ==========================================================================
def _split_keep(text: str) -> list[str]:
    """按 ``\\n`` 切分且保留行尾，保证 ``"".join(result) == text``。

    不用 ``str.splitlines(True)``：它会把 ``\\x0b`` ``\\x0c`` ``\\u2028`` 等也当换行，
    破坏"字节恒等"这个硬性质。
    """
    parts = text.split("\n")
    out = [p + "\n" for p in parts[:-1]]
    if parts[-1]:
        out.append(parts[-1])
    return out


def _content(line: str) -> str:
    """去掉行尾换行符（兼容 CRLF），保留行首缩进。"""
    return line.rstrip("\r\n")


def _indent_of(line: str) -> int:
    """行首空格数（YAML 缩进只用空格；Tab 会被视为内容的一部分）。"""
    body = _content(line)
    return len(body) - len(body.lstrip(" "))


def _is_ignorable(line: str) -> bool:
    """空行或纯注释行。"""
    stripped = _content(line).strip()
    return stripped == "" or stripped.startswith("#")


def _find_fences(lines: list[str]) -> tuple[int, int] | None:
    """定位 front-matter 围栏，返回 ``(起始行下标, 结束行下标)``。

    允许文首有 BOM 与空行。找不到闭合围栏时返回 ``None``——按 §2.2.3 的"尽量不误伤"
    原则，未闭合围栏只记 warning、按无 front-matter 处理，**不**丢弃整个文件
    （一个写得随意的 SKILL.md 不该让 skill 从库里消失）。
    """
    start = -1
    for i, line in enumerate(lines):
        if _is_ignorable(line):
            continue
        if _content(line).lstrip("﻿").strip() == "---":
            start = i
        break  # 只看第一个非空行
    if start < 0:
        return None
    for j in range(start + 1, len(lines)):
        if _content(lines[j]).strip() in _FENCES:
            return (start, j)
    return None


# ==========================================================================
# 解析：块、序列、标量
# ==========================================================================
def _split_key(body: str) -> tuple[str, str] | None:
    """把 ``key: rest`` 拆成 ``(key, rest)``；找不到合法分隔符返回 ``None``。

    必须跳过引号内的 ``:``（例如 ``name: "a: b"``），因此逐字符扫描而不做简单 split。
    """
    in_single = False
    in_double = False
    i = 0
    n = len(body)
    while i < n:
        ch = body[i]
        if ch == "\\" and in_double:
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == ":" and not in_single and not in_double:
            nxt = body[i + 1] if i + 1 < n else ""
            if nxt in (" ", "\t", ""):
                return body[:i].strip(), body[i + 1 :]
        i += 1
    return None


def _block_end(lines: list[str], start: int, hi: int, parent_indent: int) -> int:
    """返回子块（更深层缩进）的** exclusive **结束下标，尾部空行/注释不计入。"""
    last = start
    j = start
    while j < hi:
        line = lines[j]
        if _is_ignorable(line):
            j += 1
            continue
        if _indent_of(line) <= parent_indent:
            break
        last = j + 1
        j += 1
    return last


def _first_content_line(lines: list[str], lo: int, hi: int) -> int:
    """区间内第一个非空、非注释行的下标；没有则返回 ``hi``。"""
    j = lo
    while j < hi:
        if not _is_ignorable(lines[j]):
            return j
        j += 1
    return hi


def _unsupported_reason(rest: str) -> str:
    """判定值是否"合法 YAML 但超出本解析器子集"，返回原因码；空串表示支持。"""
    head = rest[:1]
    if head in ("|", ">"):
        return "block_scalar"
    if head == "&":
        return "anchor"
    if head == "*":
        return "alias"
    if rest.startswith("!!") or head == "!":
        return "explicit_tag"
    if head == "{":
        return "flow_mapping"
    if head == "[" and "]" not in rest:
        return "unclosed_inline_list"
    return ""


def _strip_inline_comment(text: str) -> str:
    """去掉引号外的行尾注释（`` # xxx``）。"""
    out: list[str] = []
    in_single = False
    in_double = False
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and in_double:
            out.append(text[i : i + 2])
            i += 2
            continue
        if ch == "'" and not in_double:
            in_single = not in_single
        elif ch == '"' and not in_single:
            in_double = not in_double
        elif ch == "#" and not in_single and not in_double and (i == 0 or text[i - 1] in " \t"):
            break
        out.append(ch)
        i += 1
    return "".join(out).strip()


def _unescape_double(text: str) -> str:
    """最小化的双引号转义还原（覆盖 YAML 常用子集）。"""
    simple = {"n": "\n", "t": "\t", "r": "\r", '"': '"', "\\": "\\", "/": "/", "0": "\0"}
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "\\" and i + 1 < n:
            nxt = text[i + 1]
            if nxt in simple:
                out.append(simple[nxt])
                i += 2
                continue
            if nxt == "u" and i + 6 <= n:
                hexs = text[i + 2 : i + 6]
                try:
                    out.append(chr(int(hexs, 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
        out.append(ch)
        i += 1
    return "".join(out)


def _parse_seq_item(raw: str, line_no: int) -> object:
    """解析单个列表项文本。"""
    item = _strip_inline_comment(raw).strip()
    if not item or item in _NULLISH:
        return ""
    head = item[:1]
    if head == "'" and item.endswith("'") and len(item) >= 2:
        return item[1:-1].replace("''", "'")
    if head == '"' and item.endswith('"') and len(item) >= 2:
        return _unescape_double(item[1:-1])
    low = item.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    if item.isdigit() or (item[:1] in "+-" and item[1:].isdigit()):
        return int(item)
    if head.isdigit() or (head in "+-." and any(c.isdigit() for c in item)):
        try:
            return float(item)
        except ValueError:
            pass
    return item


def _parse_scalar(rest: str, line_no: int) -> object:
    """解析标量值：bool / int / float / 字符串（含引号与行尾注释处理）。"""
    text = _strip_inline_comment(rest).strip()
    if text in _NULLISH:
        return ""
    head = text[:1]
    if head == "'":
        if len(text) >= 2 and text.endswith("'"):
            return text[1:-1].replace("''", "'")
        raise FrontMatterError(line_no, f"单引号未闭合：{text[:40]}")
    if head == '"':
        if len(text) >= 2 and text.endswith('"'):
            return _unescape_double(text[1:-1])
        raise FrontMatterError(line_no, f"双引号未闭合：{text[:40]}")
    low = text.lower()
    if low in _TRUE:
        return True
    if low in _FALSE:
        return False
    if text.isdigit() or (text[:1] in "+-" and text[1:].isdigit()):
        return int(text)
    if head.isdigit() or (head in "+-." and any(c.isdigit() for c in text)):
        try:
            return float(text)
        except ValueError:
            pass
    return text


def _parse_inline_list(rest: str, line_no: int) -> list[object]:
    """解析行内列表 ``[a, b, c]``（不支持嵌套与引号内逗号）。"""
    inner = rest.strip()[1:]
    if inner.endswith("]"):
        inner = inner[:-1]
    if not inner.strip():
        return []
    return [_parse_seq_item(part, line_no) for part in inner.split(",")]


def _parse_block_seq(
    lines: list[str], lo: int, hi: int, indent: int, warnings: list[dict[str, object]]
) -> list[object]:
    """解析块列表 ``- item``。"""
    items: list[object] = []
    j = lo
    while j < hi:
        line = lines[j]
        if _is_ignorable(line):
            j += 1
            continue
        if _indent_of(line) != indent:
            raise FrontMatterError(j + 1, "列表项缩进不一致")
        body = _content(line).strip()
        if body == "-":
            items.append("")
        elif body.startswith("- "):
            items.append(_parse_seq_item(body[2:], j + 1))
        else:
            raise FrontMatterError(j + 1, f"列表项缺少 '- '：{body[:40]}")
        j += 1
    return items


def _parse_block(
    lines: list[str],
    lo: int,
    hi: int,
    indent: int,
    prefix: str,
    out_fields: dict[str, object],
    out_raw: dict[str, str],
    out_key_lines: dict[str, tuple[int, int]],
    warnings: list[dict[str, object]],
) -> dict[str, object]:
    """解析一个缩进层级的 ``key: value`` 映射块（嵌套映射递归调用自身）。

    Raises:
        FrontMatterError: 结构不可恢复（交给调用方按 FR-02 跳过文件）。
    """
    fields: dict[str, object] = {}
    i = lo
    while i < hi:
        line = lines[i]
        if _is_ignorable(line):
            i += 1
            continue
        cur = _indent_of(line)
        if cur < indent:
            break  # 本层结束，交还上层
        if cur > indent:
            raise FrontMatterError(i + 1, f"缩进 {cur} 空格无法配对到任何 key（期望 {indent}）")

        body = _content(line).strip()
        if body == "-" or body.startswith("- "):
            raise FrontMatterError(i + 1, "此处不允许列表项（front-matter 必须是 key: value 映射）")

        kv = _split_key(_content(line))
        if kv is None:
            raise FrontMatterError(i + 1, f"缺少 ':' 分隔符：{body[:40]}")
        key, rest = kv[0], kv[1].strip()
        if not key:
            raise FrontMatterError(i + 1, f"key 为空：{body[:40]}")

        full = prefix + key
        start = i

        # ---- 情形 A：值为空，需要看后续子块 ----
        if rest == "":
            end = _block_end(lines, i + 1, hi, cur)
            if end == i + 1:
                fields[key] = ""
                out_fields[full] = ""
                out_key_lines[full] = (start, start)
                i += 1
                continue
            child = _first_content_line(lines, i + 1, end)
            child_indent = _indent_of(lines[child])
            child_body = _content(lines[child]).strip()

            if child_body == "-" or child_body.startswith("- "):
                value = _parse_block_seq(lines, i + 1, end, child_indent, warnings)
            elif child_indent > cur and _split_key(_content(lines[child])) is not None:
                value = _parse_block(
                    lines, i + 1, end, child_indent, full + ".",
                    out_fields, out_raw, out_key_lines, warnings,
                )
            else:
                # 例如 key 后跟一段无法归类的文本：按 raw 保留（不抛异常）
                value = "".join(lines[i + 1 : end]).strip()
                out_raw[full] = "".join(lines[i + 1 : end])
                warnings.append(
                    {"line": i + 1, "key": full, "reason": "unparsed_child_block"}
                )
            fields[key] = value
            out_fields[full] = value
            out_key_lines[full] = (start, end - 1)
            i = end
            continue

        # ---- 情形 B：合法但超出子集 ----
        reason = _unsupported_reason(rest)
        if reason:
            # 块标量（| / >）的正文是缩进子块，整段原文保留进 raw_fields
            end = _block_end(lines, i + 1, hi, cur)
            raw = "".join(lines[i:end])
            out_raw[full] = raw
            out_key_lines[full] = (start, end - 1)
            warnings.append({"line": i + 1, "key": full, "reason": reason})
            i = end
            continue

        # ---- 情形 C：行内列表 ----
        if rest.startswith("["):
            value = _parse_inline_list(rest, i + 1)
            fields[key] = value
            out_fields[full] = value
            out_key_lines[full] = (start, start)
            i += 1
            continue

        # ---- 情形 D：普通标量 ----
        value = _parse_scalar(rest, i + 1)
        fields[key] = value
        out_fields[full] = value
        out_key_lines[full] = (start, start)
        i += 1

    return fields


# ==========================================================================
# 渲染（回写用）
# ==========================================================================
def _value_style(line: str) -> str:
    """探测原有值的引号风格，回写时沿用（避免把 ``key: v`` 改成 ``key: "v"``）。"""
    kv = _split_key(_content(line))
    if kv is None:
        return "plain"
    rest = kv[1].strip()
    if rest[:1] == "'":
        return "single"
    if rest[:1] == '"':
        return "double"
    return "plain"


def _render_scalar(value: object, style: str) -> str:
    """把 Python 值渲染成 YAML 标量文本。"""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    if style == "single":
        return "'" + text.replace("'", "''") + "'"
    if style == "double":
        escaped = (
            text.replace("\\", "\\\\")
            .replace('"', '\\"')
            .replace("\n", "\\n")
            .replace("\t", "\\t")
        )
        return '"' + escaped + '"'
    return text


def _render_lines(indent: int, key: str, value: object, style: str) -> list[str]:
    """渲染一个 key 的完整行（标量一行；列表/映射多行），行尾一律带 ``\\n``。"""
    pad = " " * indent
    if isinstance(value, (list, tuple)):
        out = [f"{pad}{key}:\n"]
        for item in value:
            out.append(f"{' ' * (indent + 2)}- {_render_scalar(item, style)}\n")
        if not value:
            out[-1] = f"{pad}{key}: []\n"
        return out
    if isinstance(value, dict):
        out = [f"{pad}{key}:\n"]
        for sub_key, sub_value in value.items():
            out.extend(_render_lines(indent + 2, str(sub_key), sub_value, style))
        if not value:
            out[-1] = f"{pad}{key}: {{}}\n"
        return out
    return [f"{pad}{key}: {_render_scalar(value, style)}\n"]


def _detect_indent(fm: FrontMatter) -> int:
    """探测 front-matter 现有缩进，新增字段时沿用。"""
    if fm.has_fm and fm.fm_end > fm.fm_start + 1:
        for idx in range(fm.fm_start + 1, fm.fm_end):
            if not _is_ignorable(fm.lines[idx]):
                return _indent_of(fm.lines[idx])
    return 0


# ==========================================================================
# 对外入口
# ==========================================================================
def parse_document(text: str) -> FrontMatter:
    """解析一份 Markdown 文档（可能含 front-matter）。

    Args:
        text: 文件全文（**必须**是 ``encoding="utf-8"`` 解码后的 str）。

    Returns:
        :class:`FrontMatter`，``dump()`` 与 ``text`` 字节相等。

    Raises:
        FrontMatterError: front-matter 结构不可恢复（调用方按 FR-02 跳过文件）。
    """
    lines = _split_keep(text)
    warnings: list[dict[str, object]] = []
    fences = _find_fences(lines)
    if fences is None:
        return FrontMatter(lines=lines, warnings=warnings, has_fm=False, body_start=0)

    fm_start, fm_end = fences
    out_fields: dict[str, object] = {}
    out_raw: dict[str, str] = {}
    out_key_lines: dict[str, tuple[int, int]] = {}
    _parse_block(
        lines, fm_start + 1, fm_end, 0, "",
        out_fields, out_raw, out_key_lines, warnings,
    )
    partial = bool(out_raw)
    return FrontMatter(
        lines=lines,
        fields=out_fields,
        raw_fields=out_raw,
        key_lines=out_key_lines,
        warnings=warnings,
        partial=partial,
        has_fm=True,
        fm_start=fm_start,
        fm_end=fm_end,
        body_start=fm_end + 1,
    )


def parse_mapping(text: str) -> dict[str, object]:
    """解析一份纯 YAML 映射文本（用于 ``config.yaml``，无 front-matter 围栏）。

    Raises:
        FrontMatterError: 结构不可恢复（调用方转成 ``E_CONFIG``）。
    """
    lines = _split_keep(text)
    out_fields: dict[str, object] = {}
    out_raw: dict[str, str] = {}
    out_key_lines: dict[str, tuple[int, int]] = {}
    warnings: list[dict[str, object]] = []
    _parse_block(
        lines, 0, len(lines), 0, "",
        out_fields, out_raw, out_key_lines, warnings,
    )
    return out_fields
