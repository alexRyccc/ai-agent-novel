---
name: java-maven-build
display_name: Maven 构建与依赖管理
description: 治理依赖冲突、加速构建、保持 POM 整洁
summary: 治理依赖冲突、加速构建、保持 POM 整洁；适用：依赖冲突排查
tags: java, maven, 构建, 依赖管理, pom, 依赖冲突, 私服, jar
version: 1.0.0
author: skillforge
license: MIT
---

# Maven 构建与依赖管理

## 目标

产出无冲突、版本集中管理、构建可复现的 POM。

## 适用场景

- 依赖冲突排查
- 构建变慢
- 多模块工程整理

## 工作流

1. 用 `mvn dependency:tree` 定位冲突，优先 `dependencyManagement` 统一版本。
2. 排除传递依赖时要写清原因注释，避免后人困惑。
3. 版本号集中到 `properties` 或父 POM，禁止散落硬编码。
4. 启用 `maven-enforcer-plugin` 禁止依赖收敛失败与重复类。
5. 多模块只在必要时拆分，聚合 POM 保持零业务代码。

## 检查清单

- [ ] 是否有 SNAPSHOT 依赖进入生产构建
- [ ] 是否存在同一库多版本共存
- [ ] 是否锁定了插件版本（避免构建不可复现）
- [ ] 是否配置了内网镜像（离线/内网环境必需）

## 产出要求

交付：POM 变更 + `dependency:tree` 前后对比 + 构建耗时对比。
