---
name: ui-accessibility-wcag
display_name: 无障碍与 WCAG 2.1 AA
description: 让界面可被键盘、读屏与低视力用户正确使用
summary: 让界面可被键盘、读屏与低视力用户正确使用；适用：对外产品合规
tags: ui, 无障碍, a11y, wcag, 可访问性, 读屏, 键盘操作, 对比度不足
version: 1.0.0
author: skillforge
license: MIT
---

# 无障碍与 WCAG 2.1 AA

## 目标

达到 WCAG 2.1 AA 核心要求：可感知、可操作、可理解、健壮。

## 适用场景

- 对外产品合规
- 键盘可用性整改
- 读屏兼容

## 工作流

1. 语义化 HTML 优先：用 `<button>` 而非 `<div onclick>`，用 `<nav>/<main>/<header>` 划分地标。
2. 正文对比度 ≥ 4.5:1，大字（≥18.66px 粗体或 24px）≥ 3:1。
3. 所有交互元素可 Tab 到达，有清晰 `:focus-visible` 焦点环（禁止 `outline: none` 裸用）。
4. 图片有 `alt`（装饰性图 `alt=""`），图标按钮有 `aria-label`。
5. 表单控件有关联 `<label>`，错误提示用 `aria-describedby` 关联。
6. 动态内容变化用 `aria-live="polite"` 播报（如匹配结果更新）。
7. 提供跳至主内容的 skip link，支持键盘用户跳过导航。
8. 尊重 `prefers-reduced-motion`，为动效提供降级。

## 检查清单

- [ ] 是否所有交互都能纯键盘完成（含 Esc 关闭、方向键选择）
- [ ] 焦点是否可见且顺序符合视觉顺序
- [ ] 颜色是否是唯一信息载体（如仅靠红色表示错误）
- [ ] 文本放大到 200% 是否仍可用
- [ ] 是否有 `lang` 属性与正确的标题层级（h1→h2→h3 不跳级）
- [ ] 触控目标是否 ≥ 44×44px

## 产出要求

交付：无障碍检查清单（逐项结论）+ 修复 diff + 键盘走查记录 + 对比度实测值。
