#!/usr/bin/env python3
"""看板模板静态审计：把"看着还行"换成可核对的数字。

为什么要有这个脚本：视觉无法在本机截图验证（Edge headless 被策略挡住），
所以凡是能静态证明的都必须证明到位 —— 对比度按 WCAG 公式实算、令牌有没有
悬空引用、裸 hex/px 有没有漏网、焦点样式是否只删不补、JS 是否真的实现了
服务端契约里的每一分支。

用法：python scripts/audit_ui.py [模板路径]
退出码：有 FAIL 项时为 1。
"""

from __future__ import annotations

import re
import sys

DEFAULT = "sfx/_data/index_template.html"


# ----------------------------------------------------------------------
# 颜色与对比度
# ----------------------------------------------------------------------
def parse_hex(value: str) -> tuple[float, float, float] | None:
    v = value.strip()
    m = re.fullmatch(r"#([0-9a-fA-F]{3,8})", v)
    if not m:
        return None
    h = m.group(1)
    if len(h) in (3, 4):
        h = "".join(ch * 2 for ch in h[:3])
    elif len(h) in (6, 8):
        h = h[:6]
    else:
        return None
    return (
        int(h[0:2], 16) / 255.0,
        int(h[2:4], 16) / 255.0,
        int(h[4:6], 16) / 255.0,
    )


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4


def luminance(rgb: tuple[float, float, float]) -> float:
    r, g, b = (_lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(fg: tuple[float, float, float], bg: tuple[float, float, float]) -> float:
    l1, l2 = luminance(fg), luminance(bg)
    hi, lo = max(l1, l2), min(l1, l2)
    return (hi + 0.05) / (lo + 0.05)


# ----------------------------------------------------------------------
# 解析
# ----------------------------------------------------------------------
def split_css(html: str) -> str:
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", html, re.S)
    return "\n".join(blocks)


def split_js(html: str) -> list[str]:
    return re.findall(r"<script(?![^>]*\bsrc=)[^>]*>(.*?)</script>", html, re.S)


def collect_var_defs(css: str) -> dict[str, list[tuple[str, str]]]:
    """返回 {作用域前缀: [(变量名, 值)]}，作用域用于区分主题。"""
    out: dict[str, list[tuple[str, str]]] = {}
    # 以选择器为界切块，够用且不依赖 CSS 解析器
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        selector = m.group(1).strip().split("\n")[-1].strip()
        body = m.group(2)
        decls = re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
        if decls:
            out.setdefault(selector, []).extend((k, v.strip()) for k, v in decls)
    return out


def flatten_defs(groups: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    flat: dict[str, str] = {}
    for name, decls in groups.items():
        if name.startswith(":root") or name == "html":
            for k, v in decls:
                flat[k] = v
    return flat


def find_dark_defs(groups: dict[str, list[tuple[str, str]]]) -> dict[str, str]:
    dark: dict[str, str] = {}
    for name, decls in groups.items():
        low = name.lower()
        if "data-theme" in low and '"dark"' in low or "'dark'" in low or (
            "prefers-color-scheme" in low and "dark" in low
        ):
            for k, v in decls:
                dark[k] = v
    return dark


# ----------------------------------------------------------------------
# 主流程
# ----------------------------------------------------------------------
def main() -> int:
    path = sys.argv[1] if len(sys.argv) > 1 else DEFAULT
    html = open(path, encoding="utf-8").read()
    css = split_css(html)
    scripts = split_js(html)
    js = "\n".join(scripts)

    fails: list[str] = []
    warns: list[str] = []
    infos: list[str] = []

    infos.append(f"文件：{path}  {len(html.encode('utf-8'))} 字节  {html.count(chr(10)) + 1} 行")
    infos.append(f"内联 CSS {len(css)} 字符 / JS {len(js)} 字符 / script 块 {len(scripts)} 个")

    # ---- 占位符契约 ----
    for key in ("__SKILLS__", "__STATS__"):
        n = html.count(key)
        (infos if n == 1 else fails).append(f"占位符 {key} 出现 {n} 次（应为 1）")

    # ---- 外链 ----
    ext = len(re.findall(r'(?:src|href)\s*=\s*["\']https?://', html))
    (infos if ext == 0 else fails).append(f"外部资源引用 {ext} 个（内网要求 0）")

    # ---- 令牌 ----
    groups = collect_var_defs(css)
    flat = flatten_defs(groups)
    all_defs: dict[str, str] = {}
    for decls in groups.values():
        for k, v in decls:
            all_defs.setdefault(k, v)
    used = set(re.findall(r"var\(\s*(--[\w-]+)", css))
    # 只在 style 属性/JS 里用到的也算使用
    used |= set(re.findall(r"var\(\s*(--[\w-]+)", html))
    undefined = sorted(u for u in used if u not in all_defs)
    unused = sorted(d for d in all_defs if d not in used)
    infos.append(f"令牌：定义 {len(all_defs)} / 引用 {len(used)}")
    if undefined:
        fails.append(f"引用未定义的令牌 {len(undefined)} 个：{undefined[:6]}")
    if unused:
        (warns if len(unused) > 3 else infos).append(f"定义未使用的令牌 {len(unused)} 个：{unused[:6]}")

    # ---- 裸 hex / 裸 px（规则体内，排除令牌定义与 @media 断点）----
    rule_bodies = []
    for m in re.finditer(r"([^{}@]+)\{([^{}]*)\}", css):
        rule_bodies.append(m.group(2))
    body_text = "\n".join(rule_bodies)
    # 令牌定义行（``--sf-x: #hex``）本身就是"唯一允许出现裸色值的地方"，
    # 先剥掉再扫，否则会把 81 个令牌全报成违规（本脚本第一版就犯了这个错）。
    body_wo_defs = re.sub(r"--[\w-]+\s*:[^;]*;", "", body_text)
    bare_hex = re.findall(r"#[0-9a-fA-F]{3,8}\b", body_wo_defs)
    (infos if not bare_hex else warns).append(
        f"规则体内裸 hex {len(bare_hex)} 处" + (f"：{bare_hex[:5]}" if bare_hex else "")
    )
    bare_px = [
        v for v in re.findall(r":\s*[^;]*?(\d+px)", body_wo_defs)
    ]
    (infos if not bare_px else warns).append(f"规则体内裸 px {len(bare_px)} 处")

    # ---- 焦点与可访问性 ----
    focus_visible = css.count(":focus-visible")
    outline_none = len(re.findall(r"outline\s*:\s*(?:none|0)", css))
    if focus_visible == 0:
        fails.append("缺少 :focus-visible 样式（键盘用户无法定位）")
    else:
        infos.append(f":focus-visible 规则 {focus_visible} 处 / outline:none {outline_none} 处")
    if outline_none and focus_visible == 0:
        fails.append("存在 outline:none 但没有替代焦点样式")

    aria_live = html.count("aria-live")
    aria_label = html.count("aria-label")
    aria_hidden = html.count("aria-hidden")
    infos.append(f"aria-live {aria_live} / aria-label {aria_label} / aria-hidden {aria_hidden}")
    if aria_live == 0:
        fails.append("匹配结果区无 aria-live（屏幕阅读器收不到更新）")

    labels = re.findall(r"<label[^>]*\bfor=\"([^\"]+)\"", html)
    ids = re.findall(r"\sid=\"([^\"]+)\"", html)
    dup = {i for i in ids if ids.count(i) > 1}
    if dup:
        fails.append(f"重复 id：{sorted(dup)}")
    dangling = [f for f in labels if f not in ids]
    (fails if dangling else infos).append(
        f"label for 共 {len(labels)} 个，悬空 {len(dangling)} 个" + (f"：{dangling}" if dangling else "")
    )

    # ---- 响应式 ----
    queries = re.findall(r"@media\s*\(([^)]*)\)", css)
    infos.append(f"@media 条件 {len(queries)} 个：{sorted(set(q.strip() for q in queries))[:6]}")
    if not any("prefers-reduced-motion" in q for q in queries):
        warns.append("未处理 prefers-reduced-motion（动效无法被系统设置关闭）")
    if not any("prefers-color-scheme" in q for q in queries) and "data-theme" not in html:
        warns.append("既无 prefers-color-scheme 也无 data-theme，无法切主题")

    # ---- 对比度（取 :root 与深色/浅色覆盖后的有效值）----
    def resolve(name: str, overrides: dict[str, str]) -> str | None:
        v = overrides.get(name, flat.get(name))
        if v is None:
            return None
        v = v.strip()
        # 支持 var() 间接一层
        m = re.fullmatch(r"var\(\s*(--[\w-]+)\s*\)", v)
        if m:
            v2 = overrides.get(m.group(1), flat.get(m.group(1)))
            return v2.strip() if v2 else None
        return v

    dark_over = find_dark_defs(groups)
    if not dark_over:
        # 常见写法：:root 就是深色，浅色在 @media (prefers-color-scheme: light) 里覆盖。
        # 此时"深色"并没有独立的声明块，有效值就是 :root 本身。
        dark_over = dict(flat)
    light_over = {}
    for name, decls in groups.items():
        low = name.lower()
        if ("data-theme" in low and ("light" in low) and "dark" not in low) or (
            "prefers-color-scheme" in low and "light" in low
        ):
            for k, v in decls:
                light_over[k] = v

    pairs = [
        ("--sf-color-text", "--sf-color-bg", "正文/背景", 4.5),
        ("--sf-color-text-2", "--sf-color-bg", "次要文字/背景", 4.5),
        ("--sf-color-text-3", "--sf-color-bg", "三级文字/背景", 4.5),
        ("--sf-color-text", "--sf-color-surface", "正文/卡片", 4.5),
        ("--sf-color-text-2", "--sf-color-surface", "次要文字/卡片", 4.5),
        ("--sf-color-text-3", "--sf-color-surface", "三级文字/卡片", 4.5),
        ("--sf-color-text", "--sf-color-surface-raised", "正文/浮起层", 4.5),
        ("--sf-color-accent-fg", "--sf-color-accent", "按钮文字/主色", 4.5),
        ("--sf-color-accent-text", "--sf-color-accent-soft", "强调文字/强调底", 4.5),
        ("--sf-color-tag-fg", "--sf-color-tag-bg", "标签文字/标签底", 4.5),
        ("--sf-color-warn", "--sf-color-warn-soft", "警告/警告底", 4.5),
        ("--sf-color-danger", "--sf-color-danger-soft", "危险/危险底", 4.5),
        ("--sf-color-focus", "--sf-color-bg", "焦点环/背景", 3.0),
    ]
    for label, overrides in (("深色", dark_over), ("浅色", light_over)):
        checked = 0
        worst = (99.0, "")
        for fg_name, bg_name, desc, need in pairs:
            fg_raw, bg_raw = resolve(fg_name, overrides), resolve(bg_name, overrides)
            if not fg_raw or not bg_raw:
                continue
            fg, bg = parse_hex(fg_raw), parse_hex(bg_raw)
            if not fg or not bg:
                continue
            ratio = contrast(fg, bg)
            checked += 1
            if ratio < worst[0]:
                worst = (ratio, desc)
            if ratio + 1e-9 < need:
                fails.append(f"{label} {desc} 对比度 {ratio:.2f}:1 < {need}:1")
        if checked:
            infos.append(f"{label}主题对比度：检查 {checked} 组，最低 {worst[0]:.2f}:1（{worst[1]}）")

    # ---- JS 契约 ----
    endpoints = sorted(set(re.findall(r"""["'](/api/[\w/]+)["']""", html)))
    infos.append(f"JS 调用端点：{endpoints}")
    if "/api/match" not in endpoints:
        fails.append("JS 未调用 /api/match（路由试验台不会工作）")
    for key in ("matched", "ok", "score", "reason", "path"):
        if f"{key}" not in js:
            warns.append(f"JS 未见契约字段 {key} 的处理")
    if "AbortController" not in js and "abort" not in js.lower():
        warns.append("匹配请求无超时/中断机制")
    if "aria-live" in html and "textContent" not in js and "innerHTML" not in js:
        fails.append("结果区未做任何 DOM 更新")

    # ---- 输出 ----
    print("=" * 68)
    for line in infos:
        print("  ·", line)
    if warns:
        print("-" * 68)
        for line in warns:
            print("  !", line)
    if fails:
        print("-" * 68)
        for line in fails:
            print("  X", line)
    print("=" * 68)
    print(f"FAIL {len(fails)} / WARN {len(warns)} / 已核对项 {len(infos)}")
    return 1 if fails else 0


if __name__ == "__main__":
    raise SystemExit(main())
