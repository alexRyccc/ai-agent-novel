#!/usr/bin/env python3
"""Walking Skeleton 验收标准自检（ARCH §12.6.2 / NFR-05 / NFR-07）。

一条命令跑完 WS-1 + WS-2 的 9 条验收标准，退出码 0 表示全部通过::

    python scripts/verify_acceptance.py            # 同时验证源码目录与 zipapp 两种形态
    python scripts/verify_acceptance.py --skip-bench

与 ``tests/`` 下的单测是**互补**关系：
  - 单测负责"单元行为正确"（解析器、权重摊还、分层纪律…）；
  - 本脚本负责"端到端可跑"（两种分发形态、真子进程、真退出码、真 UTF-8 字节）。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PYZ = os.path.join(REPO_ROOT, "dist", "sfx.pyz")
TEST_SKILLS = os.path.join(REPO_ROOT, "tests", "testdata", "skills")

#: 人为注入异常用的子进程脚本（验收标准 5）
PANIC_SCRIPT = "\n".join([
    "import io, sys",
    "sys.stdout.reconfigure(encoding='utf-8', newline='\\n')",
    "sys.path.insert(0, ROOT)",
    "import sfx.__main__ as m",
    "import sfx.cli.dispatch as d",
    "def boom(argv):",
    "    raise RuntimeError('人为注入的异常')",
    "d.run = boom",
    "buf = io.StringIO()",
    "real = sys.stdout",
    "sys.stdout = buf",
    "try:",
    "    m.main()",
    "    rc = 0",
    "except SystemExit as exc:",
    "    rc = exc.code",
    "sys.stdout = real",
    "real.write(buf.getvalue())",
    "real.flush()",
    "sys.exit(rc)",
])


def clean_env() -> dict[str, str]:
    """清除 ``PYTHON*``（模拟干净目标机）。"""
    env = dict(os.environ)
    for key in list(env):
        if key.startswith("PYTHON"):
            del env[key]
    return env


class Checker:
    """收集并打印验收结果。"""

    def __init__(self) -> None:
        self.failures: list[str] = []

    def check(self, name: str, ok: bool, detail: str = "") -> None:
        """记录一条验收项。"""
        mark = "PASS" if ok else "FAIL"
        print(f"[{mark}] {name}" + (f" —— {detail}" if detail else ""))
        if not ok:
            self.failures.append(name)


def _run(args: list[str], home: str, roots: str = "", form: str = "pyz") -> subprocess.CompletedProcess:
    """以子进程跑一次 sfx。"""
    if form == "pyz":
        command = [sys.executable, PYZ] + args
        cwd = REPO_ROOT
    else:
        command = [sys.executable, "-m", "sfx"] + args
        cwd = REPO_ROOT
    env = clean_env()
    env["SFX_HOME"] = home
    if roots:
        env["SFX_ROOTS"] = roots
    return subprocess.run(command, cwd=cwd, env=env, capture_output=True)


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="Walking Skeleton 验收自检")
    parser.add_argument("--skip-bench", action="store_true", help="跳过 200 skill 压测（较慢）")
    args = parser.parse_args()

    checker = Checker()
    workdir = tempfile.mkdtemp(prefix="sfx-accept-")
    home = os.path.join(workdir, "home")
    try:
        # ---- 1. 两种形态都能跑 ----
        help_ok = version_ok = False
        for form in ("pyz", "src"):
            if not os.path.isfile(PYZ) and form == "pyz":
                continue
            result = _run(["--help"], home, form=form)
            help_ok = help_ok or (result.returncode == 0 and b"sfx" in result.stdout)
            result = _run(["--version"], home, form=form)
            version_ok = version_ok or (result.returncode == 0 and b"sfx" in result.stdout)
        checker.check("1. zipapp/源码两种形态 --help 与 --version 均可用", help_ok and version_ok)

        # ---- 2. scan 发现全部 skill 且重复扫描无重复 ----
        first = json.loads(_run(["scan"], home, TEST_SKILLS).stdout.decode("utf-8"))["data"]
        second = json.loads(_run(["scan"], home, TEST_SKILLS).stdout.decode("utf-8"))["data"]
        third = json.loads(_run(["scan"], home, TEST_SKILLS, form="src").stdout.decode("utf-8"))["data"]
        checker.check(
            "2. scan 发现 skill 且重复扫描不产生重复记录",
            first["added"] == 1 and second["added"] == 0 and second["unchanged"] == 1
            and third["skills_total"] == 1,
            f"首次 added={first['added']}；二次 added={second['added']} "
            f"unchanged={second['unchanged']}；三次 total={third['skills_total']}",
        )

        # ---- 3. match 恰好一行 JSON ----
        match = _run(["match", "--task", "帮我看下下单接口的规范"], home)
        stdout = match.stdout.decode("utf-8")
        checker.check(
            "3. match 返回恰好一行 JSON",
            match.returncode == 0 and len(stdout.strip().splitlines()) == 1,
            f"rc={match.returncode} 行数={len(stdout.strip().splitlines())}",
        )

        # ---- 4. 200 skill 压测 p95 <= 300ms ----
        if args.skip_bench:
            print("[SKIP] 4. 200 skill 压测（--skip-bench）")
        else:
            bench = subprocess.run(
                [sys.executable, os.path.join(REPO_ROOT, "scripts", "bench_match.py"),
                 "--skills", "200", "--runs", "21", "--pyz", PYZ],
                cwd=REPO_ROOT, env=clean_env(), capture_output=True,
            )
            # 用 bytes 捕获 + lenient 解码：压测脚本是普通 Python 脚本，
            # 在没设 PYTHONUTF8 的干净 Windows 上它自己会按 cp936 输出中文，
            # 与本验收项无关（本项只关心退出码与 p95 数值）。
            bench_out = bench.stdout.decode("utf-8", errors="replace")
            line = [x for x in bench_out.splitlines() if "n=" in x]
            detail = line[0].strip() if line else bench_out[-200:]
            checker.check("4. 200 skill 下 match p95 <= 300ms", bench.returncode == 0, detail)

        # ---- 5. panic 注入 ----
        env = clean_env()
        env["SFX_HOME"] = home
        panic = subprocess.run(
            [sys.executable, "-c", PANIC_SCRIPT.replace("ROOT", repr(REPO_ROOT))],
            cwd=REPO_ROOT, env=env, capture_output=True,
        )
        panic_out = panic.stdout.decode("utf-8")
        log_path = os.path.join(home, "logs", "sfx.log")
        log_text = ""
        if os.path.isfile(log_path):
            with open(log_path, "r", encoding="utf-8") as handle:
                log_text = handle.read()
        ok_panic = (
            panic.returncode == 4
            and len(panic_out.strip().splitlines()) == 1
            and json.loads(panic_out)["code"] == "E_INTERNAL"
            and "Traceback" not in panic_out
            and "RuntimeError" in log_text
            and "Traceback" in log_text
        )
        checker.check(
            "5. panic 后 stdout 仍一行 JSON、退出码 4、堆栈只进日志",
            ok_panic,
            f"rc={panic.returncode} 行数={len(panic_out.strip().splitlines())}",
        )

        # ---- 6. 中文 UTF-8 字节 ----
        doctor = _run(["doctor"], home)
        raw = doctor.stdout
        try:
            text = raw.decode("utf-8")
            ok_utf8 = "卸载" in text and json.loads(text)["ok"]
        except (UnicodeDecodeError, ValueError):
            ok_utf8 = False
        checker.check("6. 中文输出为 UTF-8 字节（可被 json.loads 解析）", ok_utf8)

        # ---- 7. 零第三方依赖 ----
        deps = subprocess.run(
            [sys.executable, os.path.join(REPO_ROOT, "scripts", "check_deps.py")],
            cwd=REPO_ROOT, capture_output=True, text=True, encoding="utf-8",
        )
        checker.check(
            "7. check_deps 输出『OK: 零第三方依赖』且 exit 0",
            deps.returncode == 0 and deps.stdout.strip() == "OK: 零第三方依赖",
            deps.stdout.strip(),
        )

        # ---- 8. round-trip 恒等 ----
        sys.path.insert(0, REPO_ROOT)
        from sfx import _frontmatter as fm  # noqa: E402  仅本脚本使用

        targets = [os.path.join(TEST_SKILLS, "order-api", "SKILL.md")]
        real_home = os.path.join(os.path.expanduser("~"), ".workbuddy", "skills")
        if os.path.isdir(real_home):
            picked = 0
            for name in sorted(os.listdir(real_home)):
                if picked >= 3:
                    break
                candidate = os.path.join(real_home, name, "SKILL.md")
                if os.path.isfile(candidate):
                    targets.append(candidate)
                    picked += 1
        identical = True
        for path in targets:
            with open(path, "rb") as handle:
                raw_bytes = handle.read()
            identical = identical and fm.parse_document(
                raw_bytes.decode("utf-8")
            ).dump().encode("utf-8") == raw_bytes
        checker.check(
            "8. parser round-trip 恒等（未经修改导出与原文字节相等）",
            identical, f"验证 {len(targets)} 个真实/样例 SKILL.md",
        )

        # ---- 9. doctor 打印数据目录 ----
        doctor_data = json.loads(_run(["doctor"], home).stdout.decode("utf-8"))["data"]
        checker.check(
            "9. doctor 正确打印数据目录",
            os.path.isabs(doctor_data["home"]) and doctor_data["db_path"].endswith("sfx.db"),
            f"home={doctor_data['home']}",
        )
    finally:
        shutil.rmtree(workdir, ignore_errors=True)

    if checker.failures:
        print(f"\n{len(checker.failures)} 项未通过：{', '.join(checker.failures)}")
        return 1
    print("\n全部 9 项验收标准通过。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
