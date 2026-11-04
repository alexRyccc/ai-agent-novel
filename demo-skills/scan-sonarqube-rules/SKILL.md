---
name: scan-sonarqube-rules
display_name: SonarQube 规则解读与修复
description: 把 SonarQube 告警转成可执行的修复动作，而非盲目忽略
summary: 把 SonarQube 告警转成可执行的修复动作，而非盲目忽略；适用：质量门禁不通过
tags: java, 代码扫描, sonarqube, 静态分析, 质量门禁, 覆盖率门槛
version: 1.0.0
author: skillforge
license: MIT
---

# SonarQube 规则解读与修复

## 目标

对每条告警给出根因、修复方案与是否需要豁免的判断。

## 适用场景

- 质量门禁不通过
- 扫描报告评审
- 技术债清理

## 工作流

1. 按严重度与类型分组：Bug / Vulnerability / Code Smell。
2. 先修 Bug 与 Vulnerability，Code Smell 按影响面排序。
3. 对每条告警定位到具体代码行，说明触发原因。
4. 能修的直接修；确需豁免的写清理由并加 `@SuppressWarnings` + 注释。
5. 修复后重扫确认门禁通过，并记录技术债变化。

## 检查清单

- [ ] 是否只关注数量而没看类型分布
- [ ] 豁免是否有理由与责任人
- [ ] 是否修复了症状而非根因（如用 try-catch 掩盖空指针）
- [ ] 新增代码的质量门禁是否比存量更严

## 产出要求

交付：告警分类统计 + 逐条修复方案 + 豁免清单（含理由）+ 重扫结果。
