#!/usr/bin/env python3
"""`sfx match` 冷启动压测（ARCH NFR-05 / §2.1 C8）。

验收标准 #4：造 200 个 skill 压测，``match`` 的 **p95 ≤ 300ms**。

方法论与架构师的实测保持一致：
  - 清除全部 ``PYTHON*`` 环境变量后再计时（本机 ``PYTHONPATH`` 会把裸启动从
    64.3ms 放大到 423ms，是冷启动头号杀手，但**目标机没有这个 shim**）；
  - n=21 次**独立进程**调用（每次都是完整冷启动），取中位数 / p95 / max；
  - 先跑 1 次预热（首次运行要建库 + 预热同义词缓存，属一次性成本）。

同时也打印"保留本机 PYTHONPATH"的对照数字，便于判断本机真实体感。

用法::

    python scripts/bench_match.py
    python scripts/bench_match.py --skills 200 --runs 21
    python scripts/bench_match.py --pyz dist/sfx.pyz     # 压测 zipapp 形态
"""

from __future__ import annotations

import argparse
import json
import math
import os
import shutil
import statistics
import subprocess
import sys
import tempfile
import time

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: 用于造数据的主题词（覆盖中英文、含同义词命中场景）
TOPICS = [
    ("数据库重构", "重构数据库访问层，抽出 Repository", ["重构", "数据库"], ["后端", "重构"]),
    ("性能优化", "优化查询性能，减少 N+1", ["性能", "数据库"], ["性能", "后端"]),
    ("单元测试", "为支付模块补充单元测试", ["测试", "支付"], ["测试"]),
    ("接口文档", "补充 REST 接口文档与示例", ["文档", "接口"], ["文档"]),
    ("缓存设计", "设计二级缓存与失效策略", ["缓存", "设计"], ["架构", "性能"]),
    ("日志规范", "统一日志格式与级别", ["日志", "规范"], ["规范"]),
    ("错误处理", "收敛异常处理与错误码表", ["错误处理", "异常"], ["规范", "后端"]),
    ("并发控制", "解决并发写入的竞态", ["并发", "数据库"], ["后端"]),
    ("权限鉴权", "补齐接口鉴权与权限校验", ["安全", "鉴权"], ["安全"]),
    ("前端组件", "抽离通用前端组件", ["前端", "组件"], ["前端"]),
]

TASKS = [
    "帮我重构这段数据库访问代码，顺便看下有没有性能问题",
    "给这个模块补单元测试，并写一份接口文档",
    "设计一下缓存失效策略，注意并发场景下的竞态",
    "统一一下内部的错误处理规范，错误码要收敛",
]


def make_skill(directory: str, index: int) -> None:
    """在 ``directory`` 下造一个 SKILL.md。"""
    label, description, triggers, tags = TOPICS[index % len(TOPICS)]
    name = f"{label}-{index:03d}"
    slug_dir = os.path.join(directory, f"skill-{index:03d}")
    os.makedirs(slug_dir, exist_ok=True)

    # 每 5 个故意不写 summary，用来验证 C-2 的缺失兜底路径
    has_summary = index % 5 != 0
    lines = ["---", f"name: {name}", f"description: {description}"]
    if has_summary:
        lines.append(f"summary: {description[:20]}（自动摘要）")
    lines.append("triggers:")
    for word in triggers:
        lines.append(f"  - {word}")
    lines.append("tags:")
    for tag in tags:
        lines.append(f"  - {tag}")
    lines.append("version: 1")
    lines.append(f"author: bench-{index:03d}")
    lines.append("---")
    lines.append("")
    lines.append(f"# {name}")
    lines.append("")
    lines.append(description)
    lines.append("")
    # 正文故意写长一些：验证路由卡确实不带正文（体积不进信封）
    lines.append("正文内容：" + ("占位文本 " * 200))
    lines.append("")
    with open(os.path.join(slug_dir, "SKILL.md"), "w", encoding="utf-8") as handle:
        handle.write("\n".join(lines))


def clean_env() -> dict[str, str]:
    """清除 ``PYTHON*`` 环境变量（模拟干净目标机）。"""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    return env


def run_once(command: list[str], cwd: str, env: dict[str, str], task: str) -> tuple[float, bool]:
    """跑一次 ``match``，返回 ``(毫秒, stdout 是否为恰好一行 JSON)``。"""
    start = time.perf_counter()
    result = subprocess.run(
        command + ["match", "--task", task],
        cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8",
    )
    spent = (time.perf_counter() - start) * 1000.0
    ok = result.returncode == 0
    if ok:
        text = result.stdout.strip()
        try:
            payload = json.loads(text)
            ok = isinstance(payload, dict) and payload.get("ok") is True
        except ValueError:
            ok = False
    return spent, ok


def percentile(values: list[float], ratio: float) -> float:
    """最近秩（nearest-rank）百分位数。"""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, int(math.ceil(ratio * len(ordered))))
    return ordered[rank - 1]


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="sfx match 冷启动压测")
    parser.add_argument("--skills", type=int, default=200, help="造多少个 skill（默认 200）")
    parser.add_argument("--runs", type=int, default=21, help="计时次数（默认 21）")
    parser.add_argument("--pyz", default="", help="压测 zipapp 产物路径（默认用源码目录形态）")
    parser.add_argument("--keep", action="store_true", help="保留临时目录（便于排查）")
    args = parser.parse_args()

    # 本脚本自身会打印中文。在没设 PYTHONUTF8 的干净 Windows 上，
    # 默认 stdout 编码是 cp936（GBK），调用方按 UTF-8 解码会炸。
    # （注意：sfx 本体不依赖这个——它靠 _boot.force_utf8() 自己保证 UTF-8，
    #   这是 ARCH P-3 的要求，也是验收标准 6 真正验证的东西。）
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    workdir = tempfile.mkdtemp(prefix="sfx-bench-")
    skills_root = os.path.join(workdir, "skills")
    home = os.path.join(workdir, "home")
    os.makedirs(skills_root, exist_ok=True)
    os.makedirs(home, exist_ok=True)
    try:
        for index in range(args.skills):
            make_skill(skills_root, index)
        print(f"[bench] 已生成 {args.skills} 个 skill：{skills_root}")

        if args.pyz:
            base = [sys.executable, os.path.abspath(args.pyz)]
            cwd = None
            form = f"zipapp（{os.path.basename(args.pyz)}）"
        else:
            base = [sys.executable, "-m", "sfx"]
            cwd = REPO_ROOT
            form = "源码目录"

        env = clean_env()
        env["SFX_HOME"] = home
        env["SFX_ROOTS"] = skills_root
        # 尽量只扫我们造的目录，避免扫到真实机器上的大量无关文件
        scan_cmd = base + ["scan"]
        scan = subprocess.run(
            scan_cmd, cwd=cwd, env=env, capture_output=True, text=True, encoding="utf-8"
        )
        if scan.returncode != 0:
            print(f"[bench] scan 失败：{scan.stdout}{scan.stderr}", file=sys.stderr)
            return 1
        payload = json.loads(scan.stdout)
        print(f"[bench] scan 结果：scanned={payload['data']['scanned_dirs']} "
              f"added={payload['data']['added']} total={payload['data']['skills_total']}")

        # 预热：首次运行要建索引/缓存，不计入 p95
        warm, ok = run_once(base, cwd or REPO_ROOT, env, TASKS[0])
        print(f"[bench] 预热一次：{warm:.1f} ms（不计入统计，ok={ok}）")

        samples: list[float] = []
        failures = 0
        for index in range(args.runs):
            task = TASKS[index % len(TASKS)]
            spent, ok = run_once(base, cwd or REPO_ROOT, env, task)
            samples.append(spent)
            if not ok:
                failures += 1
        samples.sort()

        median = statistics.median(samples)
        p95 = percentile(samples, 0.95)
        print(f"[bench] 形态：{form}")
        print(f"[bench] n={len(samples)}  中位数={median:.1f}ms  "
              f"p95={p95:.1f}ms  max={max(samples):.1f}ms  min={min(samples):.1f}ms")
        print(f"[bench] 失败次数：{failures}")

        # 对照：保留本机 PYTHONPATH（本机真实体感，非目标机口径）
        dirty = dict(os.environ)
        dirty["SFX_HOME"] = home
        dirty["SFX_ROOTS"] = skills_root
        control = [run_once(base, cwd or REPO_ROOT, dirty, TASKS[0])[0] for _ in range(3)]
        print(f"[bench] 对照（保留本机 PYTHONPATH，仅参考）："
              f"min={min(control):.1f}ms")

        verdict = "PASS" if p95 <= 300.0 and failures == 0 else "FAIL"
        print(f"[bench] 结论：{verdict}（NFR-05 要求 p95 <= 300ms）")
        return 0 if verdict == "PASS" else 1
    finally:
        if args.keep:
            print(f"[bench] 临时目录保留：{workdir}")
        else:
            shutil.rmtree(workdir, ignore_errors=True)


if __name__ == "__main__":
    sys.exit(main())
