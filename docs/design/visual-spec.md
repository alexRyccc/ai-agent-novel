# SkillForge 本地技能看板 · 视觉与组件规范（Visual Spec）

> 版本：v2.0（体验 / 分类 / 功能 / 筛选增强版）｜ 适用范围：多页控制台（SPA，单文件 HTML）｜ 作者：visual-architect（由主理人据团队结论汇编）
> 衔接：本规范与 `ux-spec.md`（体验 / IA / 交互 / 筛选逻辑）配套，是 CSS 变量与组件样式的**权威来源**；`ux-spec` 仅引用 `.sf-` 类，不另定义 CSS 变量名。前端实现以本规范 + `ux-spec` 为准。

---

## 0. 总则与硬约束

1. **令牌单一来源**：颜色 / 间距 / 字号 / 圆角 / 阴影 / 动效一律走现有 `:root` 的 `--sf-*`；规则体内不写字面量（断点 480/768/1200 字面量集中写文件底部 `@media`）。
2. **双主题**：深（默认）+ 浅，用 `@media (prefers-color-scheme: light)` 覆盖同名变量；设置页「深/浅/跟随」写 `<html data-theme>`（localStorage），同样只覆盖变量、不改规则体。
3. **零依赖、断网可用、单文件 SPA、hash 路由**：沿用现状，不新增视觉语言。
4. **动效收敛**：仅状态过渡，全部 `≤150ms`；`prefers-reduced-motion` 下关闭所有过渡与动画。
5. **不引入新色板**：状态 / 提示 / 命中率分档均复用现有 accent / warn / danger / accent-soft 系；唯一新增是**尺寸 / 层级 / 遮罩**令牌（见 §1.6）。
6. **导航结构（已裁定）**：侧边栏 6 项平铺（概览 / 技能库 / 路由试验台 / 工作台 / 团队市场 / 设置），按任务目标分页；功能域 / 来源仅作库内 / 市场筛选 facet。

## 1. 应用框架视觉

### 1.1 三栏布局
- 侧边栏 248px 常驻（折叠 64px 仅图标 + tooltip）｜ 顶栏高 56px ｜ 内容区 `max-width:1280` 居中，卡片网格 `repeat(auto-fill, minmax(280px,1fr))` gap 16。
- 间距全部取 `--sf-space-*`（4px 基准）。

### 1.2 侧边栏
- **选中态 = `accent-soft` 底色 + 左 `2px accent-line`**；选中项文字改 `--sf-text`（随主题翻转，暗色近白 / 浅色近黑，≥4.5:1，实测 ≈12.8:1）。
- 折叠 64px：图标态同样套底色 + 左条（不止一条线）；每项必须有 `aria-label`。
- 分组标题（概览 / 技能 / 协作 / 系统）仅作表现层分区、不可点击。
- 当前项 `aria-current="page"`。

### 1.3 顶栏
- 左：页标题（`sf-title`）｜ 中：全局搜索 `#sf-gsearch`（聚焦态 `accent-line` 下边）｜ 右：操作按钮 + **数据状态 pill**（`sf-status`：在线=accent / 扫描中=warn 脉动 / 失联=danger）。

### 1.4 抽屉（窄屏侧栏 / 详情）
- 暗色主题靠 **`surface-elevated` 亮面 + `border-strong` 勾边**保证层级可读；浅色主题用阴影 `0 12px 32px rgba(0,0,0,.18)`（仅抽屉 / 浮层用一处阴影）。
- 滑入 `≤150ms`；`prefers-reduced-motion` 下无滑动、直接显隐。

### 1.5 全局自报条
- 固定 header 下、`#sf-main` 上，`role="status" aria-live="polite"`；类型映射复用 `.sf-state` 左条色（error 红 / warn 黄 / info 中性）。

### 1.6 新增令牌（仅尺寸 / 层级 / 遮罩，不改动现有取值）
```
--sf-nav-w:248px; --sf-nav-w-collapsed:64px; --sf-topbar-h:56px;
--sf-surface-elevated:#232c3d (dark) / #ffffff (light);
--sf-shadow-drawer:0 12px 32px rgba(0,0,0,.45);
--sf-scrim:rgba(0,0,0,.5);
--sf-z-nav / --sf-z-topbar / --sf-z-scrim / --sf-z-drawer / --sf-z-toast
```

## 2. 核心组件视觉

### 2.1 卡片 `.sf-card`
- 头部：头像(30) / 名称(`sf-card-name`) / 版本·作者(`text-3`) / 「自动摘要」徽标(`sf-badge`，仅 `summary_fallback` 时)。
- 摘要 3 行截断；标签 `sf-tag` + `+n`；底部：状态(启用/停用) + **命中率图标**（见 2.2）。
- hover 微抬升（`translateY(-2px)` + `border-strong`，reduced-motion 取消位移）；整卡可点进详情（`role="link"` 或包 `<a>`，键盘可达）。
- 批量模式：卡片左上角勾选框（`accent` 勾选态），支持跨页批量启用/停用/导出。

### 2.2 命中率图标 `.sf-score-badge`（**v2.0 新增**）
- 形态：环形进度或水平条 + 百分比文本；紧凑档可仅显示百分比 + 色点。
- 分档配色**复用现有令牌**：高(≥80%)=`accent`；中(50–79%)=`warn`；低(<50%)=`danger` 或 `--sf-color-border-strong`（灰）。**不引入绿色等新色板**。
- 交互：`aria-label="命中率 87%"`，`:hover`/`focus` 的 tooltip 显示 SkillScore 明细；列表/网格/详情同组件复用。

### 2.3 技能详情（右抽屉 + 回退详情页）
- 头部：名称 + 版本 + 作者 + 返回 + 复制路径；元数据区：slug / 路径(`sf-path`+复制) / 完整摘要 / 全部 `sf-tag` / `triggers[]` / 状态。
- **命中率历史**：迷你条形图（用 `--sf-color-accent` 系画，不新色板）+ 趋势。
- **关联技能推荐**：同 tags / 功能域的 Top-N 卡片行。
- 操作：复制路径（is-ok/is-fail）/ 加入工作台(mock) / 分享(mock)。

### 2.4 Prompt 工作台（三栏）
- 左 草稿/模板列表；中 表单（名称/描述/正文 `textarea`，`{{var}}` 用 `accent-text` 高亮）；右 实时预览。
- 底部工具栏：保存(未保存指示 + toast + 失败回滚) / 重置 / 删除(二次确认)。

### 2.5 市场卡 `.sf-card` 变体
- 名称 / 作者 / **评分**（星用 `accent` 填充，数字 `text-2`）/ 简介 / 「安装到本机」(`sf-btn`)；安装=mock 写本地草稿。

### 2.6 设置分组表单
- 分区用 `sf-panel`；**主题切换 / 密度切换**用 `toggle`（`track=accent-soft`、`knob=bg`、on=`accent`）；破坏性设置二次确认。

### 2.7 状态块 `.sf-state`
- `loading`(蓝) / `empty-action`(warn 黄，需操作空) / `empty-neutral`(灰 `border-strong`，无结果空) / `error`(红)。左条色区分，全站统一。

### 2.8 得分 pill / 标签分面 chip
- 路由试验台得分 pill 用 `accent-text`；facet 项带**计数 badge** `.sf-tag--count`（`text-3` 小字，随筛选实时收敛）。

## 3. 分类与筛选视觉（**v2.0 增强**）

### 3.1 侧边栏分类 facet
- 分组：全部 / 功能域(Scan/Match/Prompt/埋点/部署，tags 派生) / 来源(本机/团队，仅市场页) / 作者 / 标签(多选)。
- 每项带**计数 badge**；选中态 `aria-pressed` + `accent-soft` 底；facet 组可折叠。

### 3.2 工具条（`#/library` 右栏顶部）
- 全局搜索 `#sf-gsearch`（见 3.4 高亮/建议）；排序**多字段组合控件**（见 3.5）；**筛选预设下拉**（见 3.3）；「清除筛选」(常驻显示 `显示 x / 总 y`)；「重新加载」；**视图切换**（网格/列表）。

### 3.3 保存的筛选视图 / 预设
- 下拉列出系统预设（高命中率 Prompt 类 / 从未启用 / 需复核坏技能）+ 用户命名保存的视图；保存时捕获当前 facet+搜索+排序；可删除/重命名。
- 视觉：下拉项展示筛选条件摘要（如 `Match · 高命中率 · 名称A-Z`）。

### 3.4 搜索增强视觉
- 输入即**高亮**结果中匹配片段（`mark` 用 `accent-soft` 底 + `accent-text`）；**建议下拉**（自动补全技能名/标签/作者，`sf-panel` 浮层 + 键盘上下选）；模糊 + 拼音匹配；与 facet 联动（搜索结果中再叠加过滤）。

### 3.5 排序增强视觉
- 多字段排序：可添加维度（命中率 / 更新时间 / 名称 / 版本），**拖拽调整优先级**，每维切换升降序；默认「最近/相关度」。控件用 `sf-panel` 浮层，键盘可达。

### 3.6 命中率筛选 / 排序
- facet 提供「命中率区间」(高/中/低 或滑块)；支持按命中率排序；图标见 2.2。

## 4. 跨切面纪律
- 双主题 + `data-theme` 共用同名变量、不改规则体（§0.2）。
- 4px 间距、字号阶梯、圆角、`≤150ms` 动效、`≥AA` 对比；统一 `:focus-visible` 焦点环（`2px` 背景 + `4px` 外扩）。
- `prefers-reduced-motion` 全量降级（全局 `* { transition/animation 1ms !important }` + spinner 静态 + 抽屉/toast 无滑动 + skip 常显）。

## 5. 验收清单
- [ ] 导航 6 项平铺 + `aria-current` + 折叠态 `aria-label`；分组标题不可点击。
- [ ] 双主题零特例（无新增色板）；`data-theme` 覆盖生效。
- [ ] 筛选四维（分面组合 / 保存视图 / 搜索增强 / 排序增强）+ 命中率图标全部可达且经 `dataSource` mock。
- [ ] facet 计数 badge 实时收敛；搜索高亮 + 建议下拉键盘可达。
- [ ] 状态块四态（loading/empty-action/empty-neutral/error）语义正确。
- [ ] 焦点环、`reduced-motion`、`aria-live` 与 ux-spec §6 一致。

## 6. 与 ux-spec 对齐表
| 规范概念 | 复用现有 | 新增（v2.0） |
|---|---|---|
| 状态块 | `.sf-state`(`--loading/--empty/--error`) | `.sf-state--empty-neutral`(灰)、`.sf-state--empty-action`(黄) |
| 卡片 / 命中率 | `.sf-card` `.sf-badge` `.sf-tags` | `.sf-score-badge`(命中率环/条)、`.sf-tag--count`(facet 计数) |
| 工具条 / 搜索 | `.sf-toolbar` `.sf-input` `.sf-filter` | `#sf-gsearch` 高亮/建议浮层、视图切换 |
| 排序 / 预设 | — | 多字段排序浮层、筛选预设下拉 |
| 框架 | — | `--sf-nav-w(248/64)` `--sf-topbar-h(56)` `--sf-surface-elevated` `--sf-shadow-drawer` `--sf-scrim` z-index 层级 |
| 令牌 | `:root` 全套 `--sf-*` | 仅尺寸/层级/遮罩，不改动取值 |

---

本规范 v2.0 与 `ux-spec.md` 配套，覆盖 PRD §8 的体验 / 分类 / 功能 / 筛选增强，前端实现即以此为样式权威。
