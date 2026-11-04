# SkillForge 项目说明文档

> **版本**：0.3.0　·　**更新日期**：2026-11-01
> **一句话**：SkillForge 是一个本地 AI 技能管理器——把团队积累的开发规范整理成「技能」，让内网 AI 助手（Metis）在正确的时机自动调用正确的技能，并用「真实采纳率」衡量每个技能到底好不好用。

---

## 目录

1. [项目概述](#1-项目概述)
2. [解决的问题](#2-解决的问题)
3. [核心概念](#3-核心概念)
4. [系统架构](#4-系统架构)
5. [命令行工具](#5-命令行工具)
6. [三层接入方式](#6-三层接入方式)
7. [采纳率闭环](#7-采纳率闭环)
8. [UI 设计](#8-ui-设计)
9. [技能设计](#9-技能设计)
10. [目录结构](#10-目录结构)
11. [技术要点与性能](#11-技术要点与性能)
12. [测试与质量保障](#12-测试与质量保障)
13. [已知局限与下一步](#13-已知局限与下一步)

---

## 1. 项目概述

SkillForge（内部代号 `sfx`）是一个**纯本地运行、零第三方依赖**的命令行工具 + Web 看板。它把散落在文档、Wiki、老同事脑中的开发规范，收敛成一份份结构化的「技能定义文件」（`SKILL.md`），并围绕这些技能提供三件事：

- **收进来**：扫描目录，把技能增量入库到本地 SQLite；
- **调对**：按任务描述做多信号加权匹配，选出最对口的技能；
- **看得见**：Web 看板展示技能列表、匹配试玩、以及每个技能的真实采纳率。

设计原则：**无需服务器、无需账号、无需联网、无需 pip 安装任何第三方包**。数据全部落在本机，天然适配内网 / 隔离网环境。

---

## 2. 解决的问题

内网 AI 助手（以 Metis 为例，类似 GitHub Copilot 的插件）无法自动调用本地技能——它看不到、也执行不了本机的技能定义。后果是团队积累的开发规范「存在，但 AI 用不上」。

SkillForge 用**三层接入**打通这条链路（详见[第 6 节](#6-三层接入方式)），从重到轻分别是：

| 层级 | 方式 | 谁在读 | 前提 |
| --- | --- | --- | --- |
| Tier A/B | 约定文件（`sfx sync`） | Metis 每次对话自动读 `agent.md` | 能读项目根目录文件 |
| Tier B | CLI 路由（`sfx match`） | 脚本或人按需查一次 | 能执行终端命令 |
| Tier C | 粘贴指令（`sfx prime`） | 人把指令块粘到对话开头 | 什么都不能做 |

无论走哪一层，最终都让 Metis 拿到「最匹配的技能定义文件路径」，然后去读那份 `SKILL.md` 并严格遵循。**不需要任何 API 集成，不依赖外网。**

---

## 3. 核心概念

### 3.1 技能（Skill）

一个「技能」就是一个目录 + 一份 `SKILL.md`。`SKILL.md` 是带 YAML front-matter 的 Markdown，front-matter 存元数据（名称、描述、摘要、标签、触发词），正文存可执行的工作流与规范。详见[第 9 节](#9-技能设计)。

### 3.2 路由卡（Route Card）

`sfx match` 返回的最小结果单元，字段**冻结**为六个：

```
skill_id / name / summary / path / score / reason
```

明确**不含正文**——这是防上下文爆炸的第一道闸门：Metis 拿到路由卡后，再按 `path` 去读对应的 `SKILL.md`。

### 3.3 采纳率（Load Rate）

```
采纳率 = 被采纳次数 ÷ 被推荐次数
```

- **推荐**（分母）：`sfx match` / `sfx prime` 自动记录；
- **采纳**（分子）：使用者显式 `sfx load <slug>` 上报。

不做自动推断——不根据「跑过 match 之后又打开了文件」去猜采纳，因为猜出来的采纳率进了排序会自我强化，分数好看但没意义。

### 3.4 技能评分漏斗（SkillScore）

设计上的四层漏斗：曝光（Impression）→ 加载（LoadRate）→ 采纳（AdoptionRate）→ 返工（ReworkRate）。当前版本实现了「曝光 / 采纳」两层，加权公式为 `0.3×LoadRate + 0.4×AdoptionRate + 0.3×(1−ReworkRate)`；样本量 N < 5 时对外显示「数据不足」，不给数字。

---

## 4. 系统架构

```
┌─────────────────────────────────────────────────────────┐
│                        sfx CLI                          │
│  scan · match · prime · sync · load · serve · doctor     │
└───────────────┬─────────────────────────────────────────┘
                │
        ┌───────▼────────┐
        │  cli 层（命令）  │   dispatch.py 手写 argv 解析
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │  core 层（领域） │   model / port / service
        │  matcher       │   ← 多信号加权匹配引擎
        │  parser        │   ← SKILL.md 解析（YAML 子集）
        │  router        │   ← 路由卡构建（字段冻结）
        │  scanner       │   ← 目录扫描 + 增量入库
        │  telemetry     │   ← 埋点（match / load）
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │  infra 层（基建）│   conf / logx / pathx / sqlite
        └───────┬────────┘
                │
        ┌───────▼────────┐
        │  SQLite 数据库  │   skills / sessions / call_events
        └────────────────┘
```

**分层职责**：

- **cli**：命令入口，解析参数、组装 Envelope（一行 JSON 输出契约）；
- **core**：领域逻辑，纯 Python 标准库，不碰磁盘 IO 细节；
- **infra**：基础设施，SQLite 仓储、配置解析、路径解析、日志。

### 4.1 匹配引擎（matcher）

多信号加权打分，权重可配置：

| 信号 | 默认权重 | 说明 |
| --- | --- | --- |
| keyword | 0.40 | 触发词命中（含同义词扩展，折扣 0.7） |
| tag | 0.20 | 标签命中（含 IDF 词频权重） |
| semantic | 0.25 | 语义检索（当前 off，正式版换 BM25） |
| history | 0.15 | 历史采纳率（无数据时权重摊还到其它信号） |

**关键设计**：

- **IDF 词权重**：`idf(term) = ln((N+1)/(df+1)) + 1`，封顶 2.0。稀有词（如「对比度」）比泛化词（如「ui」）得分更高，避免泛化标签把正确结果挤掉；
- **一个查询词只贡献一次**：同义词扩展不会让一个泛化词刷出 N 份分；
- **术语归一化**：`-` / `_` / `/` 折叠为空格，`spring-boot` ≡ `Spring Boot`；
- **并列决胜**：分数相同时按「证据强度」排序，保证确定性；
- **阈值**：`DEFAULT_THRESHOLD = 0.22`（实测标定，中文单触发词命中约 0.26）。

---

## 5. 命令行工具

七个命令，除 `serve` 是长驻服务外，stdout 都是**恰好一行 JSON**（加 `--human` 输出缩进多行）：

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `scan` | 扫描来源目录，技能增量入库（`--dry-run`/`--diff` 预览不写库） | `sfx scan --roots demo-skills` |
| `match` | 按任务描述匹配技能，返回路由卡（`--explain` 返回分项得分与命中词） | `sfx match "帮我写一个 Spring Boot REST 接口" --explain` |
| `prime` | 生成可粘贴给 Metis 的自包含指令块 | `sfx prime "给 Java 项目写单元测试"` |
| `sync` | 生成/更新约定文件（agent.md） | `sfx sync` |
| `load` | 上报一次「采纳」（`--undo` 撤销 / `--misfire` 标记误推荐） | `sfx load java-spring-boot-api` |
| `serve` | 启动本地 Web 看板 | `sfx serve`（默认 127.0.0.1:7788） |
| `doctor` | 打印数据目录 / 数据库 / 统计信息 | `sfx doctor` |

**统一输出契约（Envelope）**：

```json
{
  "schema": "sfx.v1",
  "ok": true,
  "code": "OK",
  "data": { "...": "..." },
  "error": null,
  "warnings": [],
  "elapsed_ms": 147,
  "engine_version": "rule+dict+v1"
}
```

退出码：`0` 成功 / `2` 用法错 / `4` 内部错误 / `5` 需人工介入。

### 5.1 可解释性（`--explain`）

匹配结果不只是给一个分数，而是回答「**为什么推荐它、我该不该信**」。`sfx match --explain` 在 `data.explain` 里返回每条命中的分项信息：

| 字段 | 含义 |
| --- | --- |
| `signals` | 各信号饱和分（keyword / tag / history，0~1） |
| `weights` | 配置权重（未归一化，实际打分会按可用信号重新摊还） |
| `matched_keywords` | 命中的触发词（原始术语） |
| `matched_tags` | 命中的标签 |
| `synonym_hits` | 同义词命中明细（查询词 → 命中词 → 折扣 0.7） |
| `idf` | 本次实际命中词的 IDF 权重 |

**置信度分级**：路由卡 `reason` 前缀 `[高]` / `[中]` / `[低]`（按 score 区间），第一名与第二名分差 < 0.05 时追加「存在并列候选，分差 X.XX」——分数硬饱和时，这一点比分数本身更有用。

> 可解释信息放 `data.explain`，路由卡六字段**保持冻结**，不破坏任何既有调用方的契约。

### 5.2 采纳反馈（`--undo` / `--misfire`）

采纳不只「加一票」，还支持纠错：

- `sfx load <slug> --undo`：撤销最近一条采纳（点错了反悔）；
- `sfx load <slug> --misfire`：标记「误推荐」（这条技能不该被推荐）。**误推荐只进统计、绝不进排序**——它用于发现「技能描述与查询不匹配」的问题，而不是惩罚技能本身。

---

## 6. 三层接入方式

### Tier A/B — 约定文件（`sfx sync`）

给项目根目录生成/更新一份 `agent.md`，内含一个**锚点块**：

```
<!-- SKILLFORGE:BEGIN -->
（技能路由索引：技能 | 摘要 | 触发词 | 定义文件路径）
<!-- SKILLFORGE:END -->
```

- 锚点块之外的内容**原样保留**；
- 若目标文件已被 Git 跟踪，**拒绝写入**（防止本机绝对路径外泄，对应错误码 `E_CONV_TRACKED_BY_GIT`）；
- `--stdout` 可预览不落盘。

### Tier B — CLI 路由（`sfx match`）

按任务描述返回路由卡（含 score、reason、定义文件路径）。适合脚本按需查询，或想看到匹配理由。

### Tier C — 粘贴指令（`sfx prime`）

生成一段**自包含**的 Markdown 指令块，粘贴到 Metis 对话开头即可。指令块只要求 Metis「读取指定文件并遵循」，**绝不要求它执行命令**（Tier C 的前提就是不能执行）。

三层共享同一套匹配引擎与数据，随时切换，不改技能本身。

---

## 7. 采纳率闭环

看板上的「采纳率」= 采纳次数 ÷ 推荐次数。`sfx match` / `sfx prime` 只记录「推荐」（分母），**采纳（分子）必须显式上报**：

```bash
sfx load java-spring-boot-api          # 用 slug
sfx load 深色模式                       # 用名字 / 目录名 / id 都可以
```

- 没有这条通道，分子恒为 0，看板只能显示「数据不足」——准确率在数学上不可能有值；
- 采纳默认挂到**最近一次 match 的会话**上，让「推荐的」和「采纳的」能对上；
- 样本量 < 5 时，`load_rate` 返回 `null`，页面显示「数据不足 · N 次」，**绝不显示 0 分**——因为「没有数据」和「真的 0%」是两件不同的事。

---

## 8. UI 设计

### 8.1 看板概览

`sfx serve` 启动的 Web 看板，是一个**单文件 HTML 模板**（`sfx/_data/index_template.html`，4703 行），服务端注入两段 JSON（`__SKILLS__` / `__STATS__`）后返回。

页面结构：

| 区块 | 内容 |
| --- | --- |
| 侧边导航 | 技能库 / 路由试验台 / 工作台 / 团队市场 / 实验室 / 设置 |
| 顶部统计卡 | 总技能数 / 已启用 / 最近扫描时间 |
| 技能库 | 卡片网格：名称、摘要、标签、作者、版本、采纳率徽标 |
| 路由试验台 | 输入任务 → 匹配 → 结果卡片（技能名 / score / 置信度标签 / 分项条形图 / 命中词 / 路径） |
| 详情页 | 完整元数据 + 采纳率三段式（推荐 N / 采纳 M / 样本不足）+ 误推荐计数 |

**路由试验台**是本看板的价值核心，结果卡片包含：

- **置信度标签**：`[高]` / `[中]` / `[低]` 彩色徽章；
- **分项得分条形图**：keyword / tag / history 三条横向条（来自 `data.explain`）；
- **命中词高亮**：命中词 chip，同义词命中标注「同义词 ×0.7」；
- **阈值提示**：结果区顶部显示「当前阈值 0.22，本次最高分 X.XX」；
- **并列提示**：第一名与第二名分差过小时，用醒目提示条提示「存在并列候选」；
- **操作区**：采纳、标记误推荐、复制路径、复制 `sfx load` 命令；
- **无结果引导**：给出「降低阈值 / 补充触发词 / 查看全部技能」三个动作，而非空白。

### 8.2 设计令牌（Design Tokens）

所有颜色、间距、字号、圆角、阴影都定义为 `:root` 上的 CSS 自定义属性，统一前缀 `--sf-`，共 **96 个**，定义与引用 1:1（无悬空、无冗余）。

| 类别 | 数量 | 示例 |
| --- | --- | --- |
| 色彩 | 23 | `--sf-color-bg` / `--sf-color-surface` / `--sf-color-accent` |
| 间距 | 8 | 4 / 8 / 12 / 16 / 24 / 32 / 48 / 64（4px 基准） |
| 字号 | 7 | 12 / 13 / 14 / 16 / 20 / 24 / 32 |
| 圆角 | 5 | 4 / 6 / 10 / 14 / 999 |
| 行高·字重 | 6 | 1.35 / 1.6；400 / 500 / 600 / 700 |
| 尺寸·描边 | 15 | 控件高度、焦点环宽度、状态条高度等 |
| 动效 | 3 | 100ms / 150ms / 缓动曲线 |
| 阴影 | 2 | 强调阴影 / 浮起阴影 |

### 8.3 配色（明暗双主题）

主色 `#6e56cf`（紫），背景 `#0d1117`（GitHub-dark 风格），正文 `#e6edf3`。

- **默认深色** + `@media (prefers-color-scheme: light)` 浅色覆盖，同一组令牌；
- **对比度全部达标**（WCAG AA ≥4.5:1）：深色主题 13 组最低 5.39:1，浅色主题最低 5.01:1；
- `data-theme` 属性支持手动切换，首屏绘制前先应用主题避免闪烁。

### 8.4 响应式

三档断点，CSS Grid + `minmax()`/`auto-fit`，无固定像素宽度、无横向滚动：

| 视口宽度 | 列数 |
| --- | --- |
| ≥1200px | 4 列 |
| 768–1199px | 2 列 |
| <768px | 1 列 |
| <480px | 统计卡纵向堆叠、按钮全宽 |

### 8.5 可访问性（a11y）

- 所有交互元素是真实 `<button>` / `<input>` / `<a>`；
- `:focus-visible` 有明确焦点环，不 `outline:none` 了事；
- 匹配结果区 `aria-live="polite"`，`label for` 12 个无悬空，图标按钮有 `aria-label`；
- `@media (prefers-reduced-motion: reduce)` 下关闭全部动效。

### 8.6 状态完整性

每个数据区块都实现 loading / empty / error 三态，不是只有成功态：

- 首屏数据来自内联 JSON，**零请求**；
- 匹配请求中按钮禁用防重复提交，`AbortController` 15s 超时；
- 采纳率未返回时先渲染「数据不足」，返回后更新，请求失败全部降级为「数据不足」而非报错。

### 8.7 安全设计

- 服务端注入 JSON 时统一转义 `<` → `\u003c`，防止技能摘要里的 `</script>` 截断脚本块（XSS 防护）；
- 看板默认只监听 `127.0.0.1`，非回环需显式 `--open`；
- 端口占用启动前探测，报 `E_USAGE` 并给换端口提示（Windows 上 `SO_REUSEADDR` 会导致端口可重复绑定，这一层探测是必须的）。

---

## 9. 技能设计

### 9.1 技能文件格式

每个技能 = 一个目录 + 一份 `SKILL.md`：

```markdown
---
name: java-spring-boot-api
display_name: Spring Boot REST API 开发
description: 按团队规范构建分层清晰、异常统一、可测试的 Spring Boot REST 接口
summary: 按团队规范构建分层清晰的 REST 接口；适用：新增或改造 REST 接口
tags: java, spring-boot, rest, api, 后端
version: 1.0.0
author: skillforge
license: MIT
---

# Spring Boot REST API 开发

## 目标
（一句话说明产出）

## 适用场景
- （什么时候用这个技能）

## 工作流
1. （第一步）
2. （第二步）
...

## 检查清单
- [ ] （可勾选的验收项）

## 产出要求
（交付什么）
```

**front-matter 字段**：

| 字段 | 作用 |
| --- | --- |
| `name` | 唯一标识（slug） |
| `display_name` | 展示名 |
| `description` | 完整描述 |
| `summary` | 路由摘要（**路由表里唯一被 LLM 看的文本**，应回答「什么时候用我」而非「我是谁」） |
| `tags` | 分类标签（给人看 + 参与匹配） |
| `triggers` / `keywords` | 触发词（召回用，可选，缺省时复用 tags） |

### 9.2 内置 30 个示例技能

`demo-skills/` 目录下 30 个技能，每个都是**真内容**（目标 / 适用场景 / 编号工作流 / 可勾选检查清单 / 产出要求），不是占位符：

**Java 开发（12 个）**：

| 技能 | 说明 |
| --- | --- |
| java-spring-boot-api | Spring Boot REST API 分层开发 |
| java-mybatis-mapper | MyBatis Mapper 与 SQL 编写 |
| java-jpa-entity | JPA 实体与关联建模 |
| java-jvm-tuning | JVM 调优与 GC 分析 |
| java-concurrency | 并发编程（线程池 / 锁） |
| java-junit5-test | JUnit5 单元测试 |
| java-maven-build | Maven 构建与依赖管理 |
| java-gradle-build | Gradle 构建脚本 |
| java-microservice-design | 微服务拆分与设计 |
| java-ddd-modeling | DDD 领域建模 |
| java-exception-handling | 异常体系设计 |
| java-logging-standard | 日志规范与可观测性 |

**代码扫描（8 个）**：

| 技能 | 说明 |
| --- | --- |
| scan-sonarqube-rules | SonarQube 规则与质量门禁 |
| scan-static-analysis | 静态分析（SpotBugs / Checkstyle） |
| scan-sast-security | SAST 安全扫描 |
| scan-sca-dependency | SCA 依赖与供应链安全 |
| scan-code-smell | 代码坏味道识别 |
| scan-complexity | 复杂度与可测试性 |
| scan-license-compliance | 开源许可证合规 |
| scan-secret-detection | 密钥与敏感信息泄露检测 |

**UI 优化（10 个）**：

| 技能 | 说明 |
| --- | --- |
| ui-design-tokens | 设计令牌落地 |
| ui-accessibility-wcag | WCAG 无障碍 |
| ui-responsive-layout | 响应式布局 |
| ui-web-performance | Web 性能（LCP / CLS / INP） |
| ui-dark-mode | 深色主题 |
| ui-component-design | 组件设计（状态完备） |
| ui-typography | 排版层级 |
| ui-color-system | 色彩系统与对比度 |
| ui-motion | 动效与过渡 |
| ui-form-ux | 表单交互与校验 |

### 9.3 技能编写规范

- **摘要要答「什么时候用」**：`summary` 是路由表里 LLM 唯一看的文本，应写成「做什么；适用：什么场景」，而不是重复「我是谁」；
- **触发词要有区分度**：只加「非专家也会这么问」的说法（如「敏感信息硬编码在代码里」），不加「优化」「检查」这类泛化动词；
- **分类标签与召回说法分开**：`tags` 是分类归属（给人看），`triggers` 是召回说法（人真正会打出来的字），混在一起会污染分类维度。

---

## 10. 目录结构

```
skillforge/
├── dist/
│   └── sfx.pyz                # zipapp 单文件产物（310 KB）
├── sfx/
│   ├── __init__.py            # 版本号常量（0.2.0）
│   ├── __main__.py            # 进程入口（UTF-8 + 看门狗 + 一行 JSON 兜底）
│   ├── _boot.py / _errors.py / _watchdog.py / _frontmatter.py / _ids.py / _res.py
│   ├── cli/                   # 七个命令 + dispatch.py
│   ├── core/                  # model / port / service（matcher·parser·router·scanner·telemetry）
│   ├── infra/                 # conf / logx / pathx / sqlite
│   └── _data/                 # 包内资源：index_template.html / migrations / synonyms.txt
├── demo-skills/               # 30 个示例技能
├── scripts/                   # build / install / check_deps / eval / audit / bench 等
├── tests/                     # 单元测试（136 项）
├── docs/                      # ARCH / PRD / 设计文档 / RELEASE-NOTES
├── agent.md                   # sync 生成的约定文件（示例）
├── start.bat / start.sh       # 一键启动器
├── README.md / LICENSE / CHANGELOG.md / pyproject.toml / .gitignore
└── release/                   # 发邮件交付包
```

**数据目录**（不在仓库里）：Windows 上 `%LOCALAPPDATA%\sfx`，Linux 桌面 `~/.local/share/sfx`，Linux 服务端 `/var/lib/sfx`。用 `sfx doctor` 查看真实路径。

---

## 11. 技术要点与性能

- **零第三方依赖**：纯标准库（`sqlite3` / `http.server` / `zipapp` / `importlib.resources`），`check_deps.py` 输出 OK；
- **单文件分发**：`dist/sfx.pyz` 是 zipapp 单文件，拷到目标机即可运行，无需 `pip install`；
- **冷启动快**：`sfx match` 冷启动约 320ms（<500ms 预算），P95 约 160ms；
- **稳定输出契约**：stdout 恒为一行 JSON，失败不阻塞调用方；
- **跨平台**：Windows / Linux / macOS，中文 Windows 下强制 UTF-8 输出（不产生 GBK 字节）。

---

## 12. 测试与质量保障

- **136 个单元测试全绿**，覆盖：匹配打分模型、SKILL.md 解析、路由卡字段冻结、同义词词典、约定文件同步、采纳上报闭环、注入防护、端口探测、空主键修复等；
- **零依赖证明**：AST 扫描脚本 `check_deps.py`；
- **匹配评测集**：`eval_match.py` 内置 31 条查询，Top-1 命中率 100%；
- **UI 静态审计**：`audit_ui.py` 核对令牌悬空、裸 hex/px、对比度、焦点、aria、断点、占位符、JS 端点，FAIL 0 才合格；
- **性能基准**：`bench_match.py` 复测匹配冷启动。

---

## 13. 已知局限与下一步

### 13.1 已知局限

1. **分数硬饱和（已缓解，未根治）**：命中 3 个满权重触发词就把信号顶到 1.000（`KEYWORD_FULL_HITS=3.0`），多个技能会并列 1.000。0.3.0 已通过「置信度分级 + 并列提示 + 分项得分」缓解——用户能看到分差和分项贡献，而不是只面对一个并列的 1.000。根治仍需换软饱和函数（会动阈值标定，暂缓）。
2. **IDF 小语料判别力有限**：当前 33 个技能，IDF 区间仅 [1.0, 2.0]。语料涨到几百个后判别力才明显增强，届时 cap 与饱和值需重新标定。
3. **采纳只能手动上报**：`sfx load` 需要使用者敲命令。能否自动上报，取决于 Metis 的能力分层（Tier 探测）——能执行命令则可在约定文件里让它自动 `sfx load`。
4. **单机版**：当前是个人/小范围验证用，不含团队账号、审核流程、多用户同步（那些是下一阶段的事）。

### 13.2 下一步方向

- **Tier 探测**：确认 Metis 到底能执行命令 / 只能读文件 / 都不能，决定采纳率能否自动上报、以及走哪一层接入；
- **软饱和 + BM25**：解决分数并列问题，提升语义检索能力；
- **团队化**：账号、审核流、技能共享、多机同步、Linux 服务端部署。

---

## 附：快速上手

```bash
# 1. 扫描技能入库（可选，默认已含 ~/.workbuddy/skills 等目录）
python dist/sfx.pyz scan --roots demo-skills

# 2. 启动看板
python dist/sfx.pyz serve

# 3. 浏览器打开 http://127.0.0.1:7788

# 4. 试匹配
python dist/sfx.pyz match "帮我写一个 Spring Boot REST 接口"

# 5. 真的用某个技能干成了活，投一票
python dist/sfx.pyz load java-spring-boot-api
```

**环境要求**：Python 3.11+，无需安装任何第三方包。
