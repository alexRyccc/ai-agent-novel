---
name: ui-web-performance
display_name: Web 性能优化（Core Web Vitals）
description: 优化 LCP、CLS、INP，让首屏快且稳定
summary: 优化 LCP、CLS、INP，让首屏快且稳定；适用：首屏慢
tags: ui, 性能, web-vitals, lcp, 前端, 首屏, 白屏, 加载慢, 体积
version: 1.0.0
author: skillforge
license: MIT
---

# Web 性能优化（Core Web Vitals）

## 目标

以真实指标为目标优化首屏与交互响应。

## 适用场景

- 首屏慢
- 布局抖动
- 交互卡顿

## 工作流

1. 先测基线：LCP、CLS、INP（用 Lighthouse / Performance 面板取实测值）。
2. LCP：优先内联关键 CSS，避免阻塞渲染的外部资源；字体用 `font-display: swap` 或系统字体。
3. CLS：所有图片/嵌入元素预留尺寸（`width`/`height` 或 `aspect-ratio`），动态内容插入不挤动布局。
4. INP：长任务拆片，事件处理避免同步重计算，重活放 `requestIdleCallback`。
5. 减少请求：内联小资源、合并 CSS/JS、去掉未使用的 CDN 依赖（内网环境尤其重要）。
6. 用 `content-visibility`、`will-change` 谨慎优化渲染，避免过度使用。

## 检查清单

- [ ] 是否所有图片/图表都有显式尺寸或比例
- [ ] 字体是否阻塞渲染
- [ ] 是否引用了外部 CDN（断网/内网会直接失败）
- [ ] 首屏是否有不必要的 JS 同步执行
- [ ] 动画是否只用 `transform`/`opacity`（避免触发重排）

## 产出要求

交付：优化前后指标对比表（LCP/CLS/INP 实测值）+ 关键改动说明。
