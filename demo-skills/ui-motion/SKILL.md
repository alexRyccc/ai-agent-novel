---
name: ui-motion
display_name: 动效与过渡
description: 用克制的动效表达状态变化，不干扰任务
summary: 用克制的动效表达状态变化，不干扰任务；适用：界面生硬缺反馈
tags: ui, 动效, 过渡, css, 交互, 动画, 缓动
version: 1.0.0
author: skillforge
license: MIT
---

# 动效与过渡

## 目标

产出目的明确、时长合理、可降级的过渡与动效。

## 适用场景

- 界面生硬缺反馈
- 动效过多影响效率
- 动画卡顿

## 工作流

1. 动效必须有目的：表达空间关系、状态变化或引导注意力，纯装饰动效克制使用。
2. 时长：微交互 100~200ms，界面转场 200~300ms，超过 400ms 会显得拖沓。
3. 缓动：进入用 `ease-out`，退出用 `ease-in`，位移用 `cubic-bezier` 自然曲线。
4. 只动 `transform` 与 `opacity`（合成层属性），避免动 `width`/`top` 触发重排。
5. 高频操作（列表滚动、频繁开关）不加动效。
6. 必须支持 `prefers-reduced-motion: reduce` 降级为无动画。

## 检查清单

- [ ] 动画属性是否只用了 transform/opacity
- [ ] 时长是否超过 400ms（显得卡顿）
- [ ] 是否尊重 reduced-motion 偏好
- [ ] 高频交互是否被强行加了动画
- [ ] 动效是否与状态语义一致（进入/退出方向）

## 产出要求

交付：动效清单（目的/时长/缓动）+ 实现代码 + reduced-motion 降级。
