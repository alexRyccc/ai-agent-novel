#!/usr/bin/env python3
"""zipapp 构建脚本（ARCH §2.3.2 / P-7）。

为什么不能 ``python -m zipapp sfx``
-----------------------------------
**zipapp 打包的是目录内容，不是目录本身**（坑 1）。直接 ``python -m zipapp sfx``
得到的 zip 里顶层是 ``__main__.py`` 而不是 ``sfx/__main__.py``，
运行时报 ``ModuleNotFoundError: No module named 'sfx'``。

因此正确做法是**打包父目录**并显式指定入口：::

    python -m zipapp <stage_dir> -o dist/sfx.pyz -m "sfx.__main__:main"

本脚本先把 ``sfx/`` 复制到干净的 ``build/_stage/sfx/``（只带包代码与 ``_data`` 资源，
不含 docs/tests/scripts），再打包父目录——既规避坑 1，也避免把 160KB 的文档打进产物。

构建后自动冒烟：``python dist/sfx.pyz --version`` 与 ``--help`` 必须成功（P-7）。

用法::

    python scripts/build.pyz.py              # 构建 + 冒烟
    python scripts/build.pyz.py --no-smoke   # 只构建
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SOURCE_PKG = os.path.join(REPO_ROOT, "sfx")
STAGE_DIR = os.path.join(REPO_ROOT, "build", "_stage")
DIST_DIR = os.path.join(REPO_ROOT, "dist")
OUTPUT = os.path.join(DIST_DIR, "sfx.pyz")
ENTRY = "sfx.__main__:main"
SHEBANG = "/usr/bin/env python3"

#: 打包时排除的噪音
EXCLUDE_DIRS = {"__pycache__", ".git", ".mypy_cache", ".pytest_cache"}


def stage() -> None:
    """把 ``sfx/`` 复制到干净的中转目录（幂等：先删后拷）。"""
    if os.path.isdir(STAGE_DIR):
        shutil.rmtree(STAGE_DIR, ignore_errors=True)
    os.makedirs(STAGE_DIR, exist_ok=True)
    target = os.path.join(STAGE_DIR, "sfx")
    shutil.copytree(SOURCE_PKG, target, ignore=shutil.ignore_patterns(*EXCLUDE_DIRS, "*.pyc"))
    print(f"[stage] {SOURCE_PKG} -> {target}")


def precompile() -> None:
    """把中转目录里的 ``.py`` 预编译成 ``__pycache__/*.pyc`` 打进产物。

    **为什么**：zipapp 里的模块每次运行都要从 zip 里读出源码并现场编译，
    本项目约 20 个模块，实测这一步要 20~30ms——占 ``sfx match`` 300ms 预算的 10%。
    ``zipimport`` 会优先使用归档内同名的 ``__pycache__/*.pyc``，于是这部分成本
    **从"每次运行"变成"构建一次"**。

    **降级安全**：``.pyc`` 带 Python 版本 magic。若目标机解释器版本不同，
    zipimport 会自动回退到同归档里的 ``.py`` 源码（源码始终一并打包），
    功能不受影响，只是少了这项优化。
    """
    import compileall

    target = os.path.join(STAGE_DIR, "sfx")
    ok = compileall.compile_dir(target, quiet=2, optimize=0)
    print(f"[precompile] {'完成' if ok else '有失败（可忽略，运行时会回退源码）'}：{target}")


def build(compress: bool = True) -> None:
    """调用 stdlib ``zipapp`` 生成单文件产物。"""
    os.makedirs(DIST_DIR, exist_ok=True)
    if os.path.exists(OUTPUT):
        os.remove(OUTPUT)
    command = [
        sys.executable, "-m", "zipapp", STAGE_DIR,
        "-o", OUTPUT,
        "-m", ENTRY,
        "-p", SHEBANG,
    ]
    if compress:
        command.append("-c")
    print(f"[zipapp] {' '.join(command)}")
    subprocess.run(command, check=True)
    size = os.path.getsize(OUTPUT)
    print(f"[build] 产物：{OUTPUT}（{size} 字节，{size / 1024:.1f} KB）")


def smoke() -> bool:
    """构建后冒烟：源码目录形态与 zipapp 形态**两种都得跑**（ARCH §2.3.3）。"""
    ok = True
    env = dict(os.environ)
    # 安装脚本绝不能设置 PYTHONPATH（实测裸启动 64ms → 423ms），这里同样清掉
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]

    cases = [
        ("源码目录形态", [sys.executable, "-m", "sfx", "--version"], REPO_ROOT),
        ("zipapp 形态", [sys.executable, OUTPUT, "--version"], None),
        ("zipapp help", [sys.executable, OUTPUT, "--help"], None),
    ]
    for name, command, cwd in cases:
        result = subprocess.run(
            command, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8"
        )
        passed = result.returncode == 0 and bool(result.stdout.strip())
        ok = ok and passed
        status = "OK  " if passed else "FAIL"
        first_line = (result.stdout or result.stderr or "").strip().splitlines()
        print(f"[smoke] {status} {name}: rc={result.returncode} "
              f"out={first_line[0][:60] if first_line else '(空)'}")
    return ok


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="构建 sfx.pyz（zipapp 单文件）")
    parser.add_argument("--no-smoke", action="store_true", help="跳过构建后冒烟")
    parser.add_argument("--no-compress", action="store_true", help="不压缩（实测反而更慢，默认压缩）")
    parser.add_argument("--no-precompile", action="store_true", help="不预编译字节码")
    args = parser.parse_args()

    if not os.path.isdir(SOURCE_PKG):
        print(f"源码包不存在：{SOURCE_PKG}", file=sys.stderr)
        return 2

    stage()
    if not args.no_precompile:
        precompile()
    build(compress=not args.no_compress)
    if args.no_smoke:
        return 0
    return 0 if smoke() else 1


if __name__ == "__main__":
    sys.exit(main())
