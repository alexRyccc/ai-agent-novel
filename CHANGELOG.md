# Changelog

本项目的所有值得注意的变更都记录在此文件。

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [Semantic Versioning](https://semver.org/lang/zh-CN/)。

## [0.3.0] - 2026-11-01

### 新增
- `sfx match --explain`：返回分项得分（keyword/tag/history）、命中词、IDF 权重、同义词折扣（放 `data.explain`，路由卡六字段冻结不变）
- 路由卡 `reason` 增加置信度分级（`[高]`/`[中]`/`[低]`），并列时提示「存在并列候选，分差 X.XX」
- `sfx load --undo`：撤销最近一条采纳；`sfx load --misfire`：标记误推荐（只进统计、不进排序）
- `sfx match --min-score`：覆盖阈值过滤；`sfx scan --dry-run`/`--diff`：预览扫描变更不写库
- 看板 `/api/match` 返回 `explain`，路由试验台展示分项条形图、置信度标签、命中词高亮、阈值提示、并列提示、无结果引导
- 看板结果卡片增加「采纳」「标记误推荐」「复制路径」操作；采纳率改为三段式「推荐 N / 采纳 M / 样本不足」；路径脱敏展示

### 变更
- 版本号 0.2.0 → 0.3.0

## [0.2.0] - 2026-10-31

### 新增
- `sfx load <slug>`：上报一次「采纳」，闭合采纳率漏斗（此前分子恒为 0，看板只能显示「数据不足」）
- 看板接入真实 `/api/scores`，采纳率来自真实埋点而非占位数据
- `sfx serve` 启动前主动探测端口，被占用时报 `E_USAGE` 并给出换端口提示
- 顶层文档补齐：`README.md`、`LICENSE`、`CHANGELOG.md`、`pyproject.toml`、`.gitignore`、`docs/RELEASE-NOTES.md`

### 修复
- 扫描时修复历史遗留的空主键（`repair_ids` 兜底，失败不影响扫描）

### 变更
- 版本号 0.1.0 → 0.2.0
