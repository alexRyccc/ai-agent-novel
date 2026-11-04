---
name: ui-component-design
display_name: 组件设计与状态完备性
description: 每个组件覆盖 loading / empty / error / 边界状态
summary: 每个组件覆盖 loading / empty / error / 边界状态；适用：新增组件
tags: ui, 组件, 设计系统, 状态, 前端, 变体, 空态
version: 1.0.0
author: skillforge
license: MIT
---

# 组件设计与状态完备性

## 目标

产出 API 清晰、状态完备、可组合复用的组件。

## 适用场景

- 新增组件
- 组件状态缺失
- 组件复用困难

## 工作流

1. 先定 API：属性命名表达语义（`variant`/`size`/`state`），避免布尔爆炸。
2. 状态必须齐备：默认、hover、focus-visible、active、disabled、loading、error。
3. 数据视图组件必须覆盖：加载中（骨架屏）、空数据、错误、部分失败。
4. 空状态要有引导动作（“去扫描”按钮），不能只写“暂无数据”。
5. 错误状态要给出可执行的下一步，而非只显示错误码。
6. 组件只负责渲染与交互，数据获取与业务逻辑外置。

## 检查清单

- [ ] 是否只有“正常”一种状态
- [ ] 空状态是否提供了下一步动作
- [ ] 加载状态是否用骨架屏而非全屏 spinner（减少布局跳动）
- [ ] 禁用态是否同时可访问（`disabled` vs `aria-disabled` 的取舍）
- [ ] 组件是否可独立预览与测试

## 产出要求

交付：组件清单 + 状态矩阵（状态 × 视觉）+ 各状态实现 + 使用示例。
