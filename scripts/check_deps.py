#!/usr/bin/env python3
"""零第三方依赖证明脚本（ARCH §9.2）。

用 AST 扫描全部源码，检出任何非标准库 import：
- 干净代码 → 打印 ``OK: 零第三方依赖`` 并 exit 0；
- 检出违规 → 列出 ``文件:行号: 模块名`` 并 exit 1。

判定依据 ``sys.stdlib_module_names``（Python 3.10+ 提供，可靠）。
注意 ``import json`` ``import sqlite3`` 这类**标准库不得误报**；
``from __future__ import annotations`` 同样属于标准库，不误报。

用法::

    python scripts/check_deps.py                 # 扫描仓库内的 sfx/ 包
    python scripts/check_deps.py --root path/to  # 扫描指定目录
    python scripts/check_deps.py --quiet         # 只回退出码

已实测（架构师）：对干净原型输出 OK 并 exit 0；注入 ``import yaml`` /
``import click`` / ``from jinja2 import Template`` 后准确报出 3 处并 exit 1。
"""

from __future__ import annotations

import argparse
import ast
import os
import sys

#: 除标准库外允许的根模块名（本项目自身）
OWN_PACKAGES = ("sfx",)


def find_violations(root: str) -> list[tuple[str, int, str]]:
    """扫描 ``root`` 下所有 ``*.py``，返回 ``(文件路径, 行号, 模块名)`` 列表。"""
    stdlib = set(sys.stdlib_module_names)
    violations: list[tuple[str, int, str]] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # 噪音目录：既加快扫描，也避免把构建产物当成源码
        dirnames[:] = [
            name for name in dirnames
            if name not in ("__pycache__", ".git", "node_modules", ".venv", "venv", "build", "dist")
        ]
        for filename in filenames:
            if not filename.endswith(".py"):
                continue
            path = os.path.join(dirpath, filename)
            try:
                with open(path, "r", encoding="utf-8") as handle:
                    source = handle.read()
            except OSError:
                continue
            try:
                tree = ast.parse(source, filename=path)
            except SyntaxError as exc:
                violations.append((path, exc.lineno or 0, f"<语法错误: {exc.msg}>"))
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        top = alias.name.split(".")[0]
                        if top not in stdlib and top not in OWN_PACKAGES:
                            violations.append((path, node.lineno, alias.name))
                elif isinstance(node, ast.ImportFrom):
                    if node.level != 0:
                        continue  # 相对导入（from . import x）必然是包内模块
                    module = node.module or ""
                    top = module.split(".")[0]
                    if top not in stdlib and top not in OWN_PACKAGES:
                        violations.append((path, node.lineno, module))
    violations.sort()
    return violations


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="断言项目零第三方依赖")
    parser.add_argument("--root", default="", help="要扫描的根目录（默认：仓库内的 sfx/）")
    parser.add_argument("--quiet", action="store_true", help="不打印成功信息")
    args = parser.parse_args()

    root = args.root
    if not root:
        here = os.path.dirname(os.path.abspath(__file__))
        root = os.path.join(os.path.dirname(here), "sfx")
    if not os.path.isdir(root):
        print(f"扫描目录不存在：{root}", file=sys.stderr)
        return 2

    violations = find_violations(root)
    if violations:
        for path, lineno, module in violations:
            print(f"{path}:{lineno}: {module}")
        print(f"发现 {len(violations)} 处第三方依赖（违反 ARCH §9.2 / P-5）", file=sys.stderr)
        return 1
    if not args.quiet:
        print("OK: 零第三方依赖")
    return 0


if __name__ == "__main__":
    sys.exit(main())
