# SkillForge

**SkillForge 是一个本地 AI 技能管理器**：把散落在各处的技能规范（`SKILL.md`）扫描入库，让内网 AI 助手（Metis）在正确的时机自动调用正确的技能，并用「真实采纳率」衡量每个技能到底好不好用。

## 它解决什么问题

内网 Metis 无法自动调用 skill——它看不到、也执行不了本机的技能定义。SkillForge 用**三层接入**打通这条链路，从重到轻分别是：

| 层级 | 方式 | 谁在读 |
| --- | --- | --- |
| Tier A/B | 约定文件（`sfx sync`） | Metis 每次对话自动读 `agent.md` |
| Tier B | CLI 路由（`sfx match` / `sfx prime`） | 脚本或人手动查一次 |
| Tier C | 粘贴指令（`sfx prime`） | 人把一段指令块粘到 Metis 对话开头 |

无论走哪一层，最终都是让 Metis 拿到「最匹配的技能定义文件路径」，然后去读那份 `SKILL.md` 并严格遵循。不需要任何 API 集成、不依赖外网。

## 快速开始

```bash
# 单文件形态（拿到 dist/sfx.pyz 后）
python dist/sfx.pyz serve
```

浏览器打开 **http://127.0.0.1:7788**，就是本地看板：技能列表 + 统计 + 匹配试玩。

> 在源码仓库里开发时，用 `python -m sfx serve` 等价。

首次使用前，先让技能入库（默认扫描 `~/.workbuddy/skills`、`~/.claude/skills`、`.cursor/rules` 三个目录，可用 `--roots` 指定别的目录）：

```bash
python dist/sfx.pyz scan --roots demo-skills
```

## 七个命令速查表

| 命令 | 作用 | 示例 |
| --- | --- | --- |
| `scan` | 扫描来源目录，把技能增量入库 | `python dist/sfx.pyz scan --roots demo-skills` |
| `match` | 按任务描述匹配技能，返回路由卡（不含正文） | `python dist/sfx.pyz match "帮我写一个 Spring Boot REST 接口"` |
| `prime` | 匹配后生成一段可直接粘贴给 Metis 的自包含指令块 | `python dist/sfx.pyz prime "帮我给 Java 项目写单元测试"` |
| `sync` | 生成/更新约定文件（`agent.md`），让 Metis 自动调技能 | `python dist/sfx.pyz sync` |
| `load` | 上报一次「采纳」，闭合准确率漏斗 | `python dist/sfx.pyz load java-spring-boot-api` |
| `serve` | 启动本地 Web 看板（默认 127.0.0.1:7788） | `python dist/sfx.pyz serve` |
| `doctor` | 打印数据目录 / 数据库 / 迁移 / 统计信息 | `python dist/sfx.pyz doctor` |

每个命令（除 `serve` 是长驻服务外）的 stdout 都是**恰好一行 JSON**；加 `--human` 会输出缩进的多行 JSON，方便人看。全局通用选项见 `python dist/sfx.pyz --help`。

## 三层接入怎么选

- **Tier A/B · 约定文件（`sfx sync`）**：给项目根目录生成/更新一份 `agent.md`，Metis 每次对话会自动读取并按索引调用技能。适合「在某个项目里长期使用、想让所有协作者自动生效」。锚点块之外的内容原样保留；若目标文件已被 Git 跟踪，会拒绝写入以免本机路径外泄。
- **Tier B · CLI 路由（`sfx match`）**：按任务描述返回最匹配的技能路由卡（含 `score`、`reason`、定义文件路径）。适合「脚本里按需查询，或想看到匹配理由」。
- **Tier C · 粘贴指令（`sfx prime`）**：生成一段自包含的 Markdown 指令块，直接粘贴到 Metis 对话开头即可。适合「零配置先试一下，或不便写约定文件的场景」。

三者共享同一套匹配引擎与数据，随时可以切换，不用改技能本身。

## 采纳率闭环：为什么必须有 `sfx load`

看板上的「采纳率 = 被采纳次数 ÷ 被推荐次数」。`sfx match` / `sfx prime` 只记录「推荐」（分母），**采纳（分子）必须由使用者显式上报**：

```bash
python dist/sfx.pyz load java-spring-boot-api
```

没有这条上报通道，分子恒为 0，看板只能一直显示「数据不足」——准确率在数学上不可能有值，页面做得再漂亮也只是空壳。所以每次某个技能真的帮你干成了活，敲一行 `sfx load <slug>` 就是「投票」。`<slug>` 可以是 slug、技能名、目录名或 id 的任意一种写法。

> 采纳不做自动推断：不根据「跑过 match 之后又打开了文件」去猜。猜出来的采纳率进了排序会自我强化，分数好看但没意义。

## 目录结构

```
skillforge/
├── dist/
│   └── sfx.pyz                # zipapp 单文件产物（python scripts/build.pyz.py 构建）
├── sfx/
│   ├── __init__.py            # 版本号常量
│   ├── __main__.py            # 进程入口（UTF-8 + 看门狗 + 一行 JSON 兜底）
│   ├── _boot.py / _errors.py / _watchdog.py / _frontmatter.py / _ids.py / _res.py
│   ├── cli/                   # 七个命令：cmd_scan / cmd_match / cmd_prime /
│   │                          #   cmd_sync / cmd_load / cmd_serve / cmd_doctor + dispatch.py
│   ├── core/                  # 领域逻辑：model / port / service（matcher·parser·router·scanner·telemetry）
│   ├── infra/                 # 基础设施：conf / logx / pathx / sqlite
│   └── _data/                 # 包内资源：index_template.html / migrations / synonyms.txt
├── demo-skills/               # 30 个示例技能（java-* / scan-* / ui-*），每个含 SKILL.md
├── scripts/                   # build.pyz.py / install.sh / install.ps1 / check_deps.py 等
├── tests/                     # 单元测试（136 项）
├── docs/                      # skillforge-ARCH.md / skillforge-PRD.md / 设计文档
├── agent.md                   # sync 生成的约定文件（示例）
├── start.bat / start.sh       # 一键启动器（扫描 + 启动看板 + 自动开浏览器）
└── README.md
```

数据不在仓库里：Windows 上落在 `%LOCALAPPDATA%\sfx`，Linux 桌面落在 `~/.local/share/sfx`。用 `sfx doctor` 查看真实路径。

## 常见问题

**端口被占用（7788）**
`sfx serve` 启动前会主动探测端口，被占用时报 `E_USAGE`，并给出可执行提示：

```
端口 7788 已被占用（可能是一个没关掉的看板进程）
换一个端口：sfx serve --port 7789；或先结束占用进程（Windows：netstat -ano | findstr :7788）
```

**Windows 中文路径 / 中文输出乱码**
所有文件 IO 都显式 `encoding="utf-8"`，进程启动第一行就强制 stdout/stderr 为 UTF-8，中文 Windows 上不会输出 GBK 字节。数据目录是 `%LOCALAPPDATA%\sfx`（不是 `~/.sfx`），以 `sfx doctor` 打印的绝对路径为准。

**数据在哪、怎么卸载**
`sfx doctor` 会打印 `home` / `db_path` / 日志路径等全部落盘位置。完全卸载 = 删除那个数据目录（Windows 另需删除安装目录下的 `sfx.cmd` 与 PATH 条目），不残留注册表、不残留服务。

**Metis 还是没自动调技能**
确认三点：① 目标项目根目录下有 `agent.md` 且含 `<!-- SKILLFORGE:BEGIN -->` 锚点块（`sfx sync --stdout` 可预览）；② 技能已入库（`sfx scan` 后 `sfx doctor` 里 `skills > 0`）；③ 任务描述确实命中某技能（`sfx match "..."` 看 `match_count`）。

## 技术要点

- **零第三方依赖**：纯标准库（`sqlite3` / `http.server` / `zipapp`），`python scripts/check_deps.py` 输出 OK。
- **单文件分发**：`dist/sfx.pyz` 是 zipapp 单文件（约 310 KB），拷到目标机即可运行，无需 `pip install`。
- **冷启动快**：实测 `sfx match` 冷启动约 320ms（含解释器启动，<500ms），远低于 3 秒看门狗预算。
- **稳定输出契约**：stdout 恒为一行 JSON，任何失败都不阻塞调用方；退出码 `0` 成功 / `2` 用法错 / `4` 内部错误 / `5` 需人工介入。
- **本地单机看板**：默认只监听 127.0.0.1，断网可用（页面零 CDN）。

## 环境要求

- Python **3.11+**（Windows / Linux / macOS 均可）
- 无需安装任何第三方包
