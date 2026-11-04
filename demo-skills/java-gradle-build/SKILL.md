---
name: java-gradle-build
display_name: Gradle 构建脚本
description: 编写可维护、可缓存、版本集中的 Gradle 构建
summary: 编写可维护、可缓存、版本集中的 Gradle 构建；适用：迁移或新建 Gradle 工程
tags: java, gradle, 构建, 依赖管理, 构建缓存, plugin
version: 1.0.0
author: skillforge
license: MIT
---

# Gradle 构建脚本

## 目标

产出使用版本目录、任务配置延迟化、构建可缓存的 Gradle 工程。

## 适用场景

- 迁移或新建 Gradle 工程
- 构建速度优化
- 多模块依赖整理

## 工作流

1. 依赖版本集中到 `gradle/libs.versions.toml` 版本目录。
2. 用 `plugins {}` 块，不用遗留的 `apply plugin`。
3. 避免在配置阶段做耗时操作，必要时用 `configuration avoidance`。
4. 启用构建缓存与并行：`org.gradle.caching=true`、`org.gradle.parallel=true`。
5. 自定义任务显式声明 `inputs` / `outputs` 以支持增量构建。

## 检查清单

- [ ] 是否有硬编码的仓库地址（内网应指向私服）
- [ ] 是否所有依赖都走了版本目录
- [ ] 构建是否可复现（无动态版本 `+`）
- [ ] 是否开启了构建缓存

## 产出要求

交付：构建脚本 + 配置说明 + 构建耗时前后对比。
