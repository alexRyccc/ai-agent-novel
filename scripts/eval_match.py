#!/usr/bin/env python3
"""``sfx match`` 离线排序质量评测（ARCH §7.2 质量门禁）。

为什么要有这个脚本
------------------
matcher 的打分公式（关键词 / 同义词 / 标签 / IDF）任何一处改动都会同时影响
30 条查询的排序结果，**靠肉眼抽查不可能判断改动是净收益还是净损失**。
这里把"排序质量"变成一个可复跑的数字：Top-1 命中率 / Top-3 命中率。

设计约束
--------
- **只用标准库**（本项目零第三方依赖，见 ``scripts/check_deps.py``）；
- **走真实 CLI**（``subprocess`` 调 ``python -m sfx match``），而不是在进程内
  直接调 ``matcher.match()``：只有这样才能覆盖"读库 → 读词典缓存 → 打分 →
  阈值过滤 → 序列化"的整条链路，避免"函数级对、CLI 级错"的假绿灯；
- 语料（30 条查询 + 期望技能）与 demo-skills 的 30 个技能一一对应；
- ``|`` 分隔表示"任一命中即算对"（有些查询天然有两种合理答案）。

用法::

    python scripts/eval_match.py                 # 打表 + 结论
    python scripts/eval_match.py --verbose       # 额外打印 Top-3 的 reason
    python scripts/eval_match.py --min-top1 0.85 # 低于该命中率则 exit 1
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time

#: 评测以**仓库根目录**为 cwd 跑 ``python -m sfx``（与 bench_match.py 口径一致）
REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

#: ``(查询, 期望 slug)``；``|`` 分隔表示任一都算对
QUERIES: tuple[tuple[str, str], ...] = (
    ("帮我写一个 Spring Boot 接口", "java-spring-boot-api"),
    ("MyBatis 的动态条件怎么写", "java-mybatis-mapper"),
    ("排查慢 SQL", "java-mybatis-mapper"),
    ("JPA 实体关联怎么配", "java-jpa-entity"),
    ("JVM 调优", "java-jvm-tuning"),
    ("线程池怎么配置", "java-concurrency"),
    ("写单元测试", "java-junit5-test"),
    ("pom 依赖冲突", "java-maven-build"),
    ("gradle 构建太慢", "java-gradle-build"),
    ("微服务怎么拆", "java-microservice-design"),
    ("领域模型怎么建模", "java-ddd-modeling|java-microservice-design"),
    ("异常处理乱", "java-exception-handling"),
    ("日志打得不规范", "java-logging-standard"),
    ("代码扫描发现安全问题", "scan-sast-security"),
    ("SpotBugs 报错一堆", "scan-static-analysis"),
    ("SonarQube 质量门禁不过", "scan-sonarqube-rules"),
    ("依赖漏洞扫描", "scan-sca-dependency"),
    ("代码复杂度太高怎么重构", "scan-complexity"),
    ("检查开源许可证合规", "scan-license-compliance"),
    ("检测硬编码密钥", "scan-secret-detection"),
    ("设计系统怎么落地", "ui-design-tokens"),
    ("无障碍不达标", "ui-accessibility-wcag"),
    ("移动端适配", "ui-responsive-layout"),
    ("前端首屏太慢", "ui-web-performance"),
    ("配置深色模式", "ui-dark-mode"),
    ("组件状态不全", "ui-component-design"),
    ("字体排版层级混乱", "ui-typography"),
    ("优化页面配色和对比度", "ui-color-system"),
    ("过渡动效太生硬", "ui-motion"),
    ("表单校验提示不友好", "ui-form-ux"),
    ("生成一个像素游戏角色", "pixel-asset-forge"),
)

#: ``sfx match`` 输出里单条结果用到的字段
_WANTED_KEYS = ("name", "score", "reason")


def run_match(task: str) -> tuple[list[dict], str, float, str]:
    """跑一次 ``sfx match``。

    Args:
        task: 任务描述原文。

    Returns:
        ``(Top-N 结果列表, 信封 code, 墙钟毫秒, 错误说明)``。
        ``错误说明`` 非空时表示这次调用失败（但评测继续跑剩下的查询）。
    """
    command = [sys.executable, "-m", "sfx", "match", "--task", task]
    start = time.perf_counter()
    try:
        completed = subprocess.run(
            command,
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:  # 解释器都起不来，直接报出来
        return [], "", 0.0, f"无法启动子进程：{exc}"
    spent_ms = (time.perf_counter() - start) * 1000.0

    stdout = (completed.stdout or "").strip()
    if not stdout:
        return [], "", spent_ms, f"exit={completed.returncode} 空输出：{(completed.stderr or '')[:200]}"
    try:
        envelope = json.loads(stdout)
    except ValueError:
        return [], "", spent_ms, f"输出不是 JSON：{stdout[:200]}"
    if not isinstance(envelope, dict):
        return [], "", spent_ms, "信封不是对象"

    data = envelope.get("data")
    if not isinstance(data, dict):
        return [], str(envelope.get("code", "")), spent_ms, "信封缺少 data"
    raw_matched = data.get("matched")
    if not isinstance(raw_matched, list):
        return [], str(envelope.get("code", "")), spent_ms, "data.matched 不是列表"

    matched: list[dict] = []
    for item in raw_matched:
        if not isinstance(item, dict):
            continue
        matched.append({key: item.get(key, "") for key in _WANTED_KEYS})
    return matched, str(envelope.get("code", "")), spent_ms, ""


def expected_names(spec: str) -> tuple[str, ...]:
    """把 ``a|b`` 形式展开成可接受名称元组。"""
    return tuple(part.strip() for part in spec.split("|") if part.strip())


def main() -> int:
    """命令行入口。"""
    parser = argparse.ArgumentParser(description="sfx match 排序质量评测")
    parser.add_argument("--verbose", action="store_true", help="打印每条查询 Top-3 的 reason")
    parser.add_argument(
        "--min-top1", type=float, default=0.85,
        help="Top-1 命中率下限（默认 0.85，低于则 exit 1）",
    )
    args = parser.parse_args()

    # 本脚本打印中文；干净 Windows 的默认 stdout 是 cp936，先钉成 UTF-8。
    reconfigure = getattr(sys.stdout, "reconfigure", None)
    if reconfigure is not None:
        reconfigure(encoding="utf-8")

    top1_hits = 0
    top3_hits = 0
    failures: list[str] = []
    total_ms = 0.0
    slowest = (0.0, "")

    print(f"[eval] 共 {len(QUERIES)} 条查询（语料：demo-skills + ~/.workbuddy/skills）")
    print("")

    for index, (task, spec) in enumerate(QUERIES, start=1):
        wanted = expected_names(spec)
        matched, code, spent_ms, error = run_match(task)
        total_ms += spent_ms
        if spent_ms > slowest[0]:
            slowest = (spent_ms, task)

        names = [str(item.get("name", "")) for item in matched]
        top1 = names[0] if names else ""
        ok1 = top1 in wanted
        ok3 = any(name in wanted for name in names[:3])
        top1_hits += 1 if ok1 else 0
        top3_hits += 1 if ok3 else 0
        if not ok1:
            failures.append(task)

        if error:
            print(f"{index:02d}. [ERR ] {task}  —— {error}")
            continue

        rank_hint = "PASS" if ok1 else ("T3  " if ok3 else "MISS")
        head = f"{index:02d}. [{rank_hint}] {task}  ->  "
        if not matched:
            print(head + f"(无命中，code={code})  期望 {spec}")
            continue
        shown = " / ".join(f"{item['name']}({float(item['score']):.3f})" for item in matched[:3])
        print(head + shown + f"   期望 {spec}")

        if args.verbose:
            for rank, item in enumerate(matched[:3], start=1):
                print(f"      #{rank} {item['name']}({float(item['score']):.3f}) {item['reason']}")

    count = len(QUERIES)
    rate1 = top1_hits / count if count else 0.0
    rate3 = top3_hits / count if count else 0.0
    print("")
    print(f"[eval] Top-1 命中率：{top1_hits}/{count} = {rate1 * 100:.1f}%")
    print(f"[eval] Top-3 命中率：{top3_hits}/{count} = {rate3 * 100:.1f}%")
    print(f"[eval] 总耗时：{total_ms:.0f}ms（平均 {total_ms / count:.0f}ms/条，"
          f"最慢 {slowest[0]:.0f}ms：{slowest[1]}）")
    if failures:
        print(f"[eval] 未命中 Top-1 的查询：{'；'.join(failures)}")
    verdict = "PASS" if rate1 >= args.min_top1 else "FAIL"
    print(f"[eval] 结论：{verdict}（要求 Top-1 >= {args.min_top1 * 100:.0f}%）")
    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
