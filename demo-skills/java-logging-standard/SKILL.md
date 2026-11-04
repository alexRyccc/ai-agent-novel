---
name: java-logging-standard
display_name: 日志规范与可观测性
description: 输出结构化、可检索、不含敏感信息的日志
summary: 输出结构化、可检索、不含敏感信息的日志；适用：日志混乱难以排查
tags: java, 日志, logback, 可观测性, 排查, 结构化日志, 脱敏, traceid
version: 1.0.0
author: skillforge
license: MIT
---

# 日志规范与可观测性

## 目标

产出分级合理、字段结构化、能支撑线上排障的日志。

## 适用场景

- 日志混乱难以排查
- 接入日志平台
- 脱敏整改

## 工作流

1. 用 SLF4J API + 占位符（`log.info("order={}", id)`），不用字符串拼接。
2. 级别语义：ERROR 需人工介入、WARN 可自愈、INFO 关键业务节点、DEBUG 排障细节。
3. 关键链路传递 traceId，并写入 MDC 输出到每条日志。
4. 结构化输出（JSON encoder）便于日志平台检索。
5. 敏感字段（手机号、身份证、token、密码）必须脱敏或不记录。

## 检查清单

- [ ] 是否有 `System.out.println` 残留
- [ ] 异常日志是否传了异常对象（`log.error("x", e)`）
- [ ] 是否在循环里打大量 INFO 日志
- [ ] 日志中是否有明文敏感信息
- [ ] 日志文件是否配置了轮转与保留上限

## 产出要求

交付：日志配置 + 关键路径埋点清单 + 脱敏规则说明。
